"""Round-level autonomous research loop controller."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from knowledgegraph.demand_discovery.domain.candidate_synthesis import (
    CandidateSynthesisDraft,
    synthesize_candidate_from_judgement,
)
from knowledgegraph.demand_discovery.domain.evidence_quality import (
    evidence_has_strong_or_direct_support,
)
from knowledgegraph.demand_discovery.domain.judgement import JudgementReport
from knowledgegraph.demand_discovery.domain.judgement_plan import (
    assess_next_round_plan,
    build_repaired_next_round_plan,
)
from knowledgegraph.demand_discovery.domain.models import (
    DomainTraceEvent,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.open_search import (
    OpenSearchPlan,
    OpenSourceBodyArtifact,
    OpenSourceLead,
    SourceQualityAssessment,
)
from knowledgegraph.demand_discovery.domain.research_state import (
    ReadingQueue,
    ResearchLead,
    ResearchRound,
)
from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry
from knowledgegraph.demand_discovery.domain.source_strategy import SourceStrategy
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.harness.judge_plan_routing import (
    open_search_queries_from_judgement as routed_open_search_queries_from_judgement,
    open_search_tasks_from_judgement as routed_open_search_tasks_from_judgement,
    worker_assignments_from_judgement,
)
from knowledgegraph.demand_discovery.harness.judge_agent import run_judge_agent_for_round
from knowledgegraph.demand_discovery.harness.worker_report import WorkerReport, parse_worker_text


@dataclass(frozen=True)
class StopDecision:
    should_stop: bool
    reason: str


@dataclass(frozen=True)
class OpenSearchTriggerDecision:
    should_trigger: bool
    reason: str


def evaluate_stop_conditions(
    *,
    round_index: int,
    max_rounds: int,
    new_strong_evidence_count: int,
    judgement: JudgementReport,
    budget_exhausted: bool = False,
    consecutive_no_new_sources: int = 0,
) -> StopDecision:
    if round_index >= max_rounds:
        return StopDecision(True, "max_rounds")
    if budget_exhausted:
        return StopDecision(True, "budget_exhausted")
    if judgement.stop_or_continue == "needs_human_steer":
        return StopDecision(True, "blind_spots_need_human")
    if consecutive_no_new_sources >= 2:
        return StopDecision(True, "consecutive_no_new_sources")
    if judgement.stop_or_continue == "stop":
        return StopDecision(True, "judge_stop")
    if new_strong_evidence_count <= 0 and not _has_v1_follow_up_tasks(
        judgement.next_round_plan
    ):
        return StopDecision(True, "no_new_strong_evidence")
    return StopDecision(False, "continue")


class ResearchLoopController:
    def __init__(
        self,
        *,
        run_id: str,
        topic: str,
        strategy: SourceStrategy,
        store: DomainStore,
        registry: SourceRegistry,
        max_rounds: int,
        judge_provider_factory: Callable[[], Any] | None = None,
        judge_sessions_dir: str | Path | None = None,
    ) -> None:
        self.run_id = run_id
        self.topic = topic
        self.strategy = strategy
        self.store = store
        self.registry = registry
        self.max_rounds = max(1, max_rounds)
        self.judge_provider_factory = judge_provider_factory
        self.judge_sessions_dir = Path(
            judge_sessions_dir or Path("outputs") / "runs" / run_id / "judge"
        )
        self.trace: list[str] = ["source_strategy"]
        self.candidate_synthesis: CandidateSynthesisDraft | None = None

    def run_fake_loop(self) -> dict[str, Any]:
        return asyncio.run(self.run_fake_loop_async())

    async def run_fake_loop_async(self) -> dict[str, Any]:
        round_rows: list[dict[str, Any]] = []
        self._append_domain_trace(
            event_type="source_strategy_selected",
            target_type="SourceStrategy",
            target_id=self.strategy.strategy_id,
            output_refs=[self.strategy.strategy_id],
            summary=f"selected source strategy {self.strategy.strategy_id}",
            payload={
                "selected_sources": [
                    {
                        "source_name": source.source_name,
                        "source_tier": source.source_tier,
                        "entry_urls": list(source.entry_urls),
                    }
                    for source in self.strategy.selected_sources
                ]
            },
        )
        previous_judgement: JudgementReport | None = None
        active_open_search_plan: OpenSearchPlan | None = None
        consecutive_no_new_sources = 0
        for index in range(1, self.max_rounds + 1):
            if active_open_search_plan is not None:
                active_open_search_plan = self._mark_open_search_plan_status(
                    active_open_search_plan,
                    "running",
                )
            research_round, reports, new_strong_evidence_count, new_source_count = self._run_fake_round(
                index,
                previous_judgement=previous_judgement,
                active_open_search_plan=active_open_search_plan,
            )
            if new_source_count <= 0:
                consecutive_no_new_sources += 1
            else:
                consecutive_no_new_sources = 0
            judgement = await self._judge_round(
                research_round=research_round,
                reports=reports,
            )
            next_open_search_plan = self._maybe_create_open_search_plan(
                round_index=index,
                research_round=research_round,
                judgement=judgement,
                new_strong_evidence_count=new_strong_evidence_count,
                consecutive_no_new_sources=consecutive_no_new_sources,
            )
            if next_open_search_plan is not None:
                research_round = ResearchRound(
                    **{
                        **research_round.to_dict(),
                        "status": "judged",
                        "judgement_id": judgement.judgement_id,
                        "next_round_plan": judgement.next_round_plan,
                    }
                )
                self.store.upsert_research_round(research_round)
                self.store.upsert_judgement_report(judgement)
                self.trace.append("judgement")
                round_rows.append(_round_row(research_round, judgement))
                previous_judgement = judgement
                active_open_search_plan = next_open_search_plan
                continue
            decision = evaluate_stop_conditions(
                round_index=index,
                max_rounds=self.max_rounds,
                new_strong_evidence_count=new_strong_evidence_count,
                judgement=judgement,
                consecutive_no_new_sources=consecutive_no_new_sources,
            )
            if decision.should_stop:
                judgement.stop_or_continue = "stop"
                if active_open_search_plan is not None:
                    active_open_search_plan = self._mark_open_search_plan_status(
                        active_open_search_plan,
                        "completed",
                    )
                research_round = ResearchRound(
                    **{
                        **research_round.to_dict(),
                        "status": "stopped",
                        "judgement_id": judgement.judgement_id,
                        "next_round_plan": judgement.next_round_plan,
                        "stop_reason": decision.reason,
                    }
                )
                self.store.upsert_research_round(research_round)
                self.store.upsert_judgement_report(judgement)
                self.trace.append("judgement")
                self.candidate_synthesis = synthesize_candidate_from_judgement(
                    judgement,
                    self.store,
                )
                if self.candidate_synthesis.status == "synthesized":
                    self._append_domain_trace(
                        event_type="candidate_synthesized",
                        target_type="CandidateDemand",
                        target_id=self.candidate_synthesis.candidate_id,
                        input_refs=[
                            judgement.judgement_id,
                            *self.candidate_synthesis.evidence_ids,
                        ],
                        output_refs=[self.candidate_synthesis.candidate_id],
                        summary=(
                            "candidate synthesized from judgement "
                            f"{judgement.judgement_id}"
                        ),
                        decision=self.candidate_synthesis.status,
                        rationale=self.candidate_synthesis.rationale,
                        payload={
                            "open_questions": list(
                                self.candidate_synthesis.open_questions
                            )
                        },
                    )
                self.trace.append("candidate_synthesis")
                round_rows.append(_round_row(research_round, judgement))
                break
            research_round = ResearchRound(
                **{
                    **research_round.to_dict(),
                    "status": "judged",
                    "judgement_id": judgement.judgement_id,
                    "next_round_plan": judgement.next_round_plan,
                }
            )
            self.store.upsert_research_round(research_round)
            self.trace.append("judgement")
            round_rows.append(_round_row(research_round, judgement))
            previous_judgement = judgement
        return {
            "rounds": round_rows,
            "trace": list(self.trace),
            "candidate_synthesis": (
                self.candidate_synthesis.to_dict()
                if self.candidate_synthesis is not None
                else None
            ),
            "open_search_plans": [
                plan.to_dict() for plan in self.store.open_search_plans.values()
            ],
        }

    async def run_network_loop(
        self,
        *,
        seed_urls: list[str],
        execute_round: Callable[..., Awaitable[Any]],
    ) -> dict[str, Any]:
        """Run Phase 5 round control around real network worker execution.

        The network worker is an implementation detail of a round; it may fetch
        pages and create SourceRecord/EvidenceCard rows, but the controller owns
        ResearchRound, ReadingQueue, judge, stop/continue, and candidate
        synthesis.
        """

        round_rows: list[dict[str, Any]] = []
        network_worker_runs: list[dict[str, Any]] = []
        self._append_domain_trace(
            event_type="source_strategy_selected",
            target_type="SourceStrategy",
            target_id=self.strategy.strategy_id,
            output_refs=[self.strategy.strategy_id],
            summary=f"selected source strategy {self.strategy.strategy_id}",
            payload={
                "selected_sources": [
                    {
                        "source_name": source.source_name,
                        "source_tier": source.source_tier,
                        "entry_urls": list(source.entry_urls),
                        "planned_queries": list(getattr(source, "planned_queries", [])),
                    }
                    for source in self.strategy.selected_sources
                ],
                "seed_urls": list(seed_urls),
            },
        )
        previous_judgement: JudgementReport | None = None
        active_open_search_plan: OpenSearchPlan | None = None
        consecutive_no_new_sources = 0
        for index in range(1, self.max_rounds + 1):
            if active_open_search_plan is not None:
                active_open_search_plan = self._mark_open_search_plan_status(
                    active_open_search_plan,
                    "running",
                )
            planned_tasks = self._plan_worker_assignments(
                previous_judgement,
                next_round_id=f"round-{index}",
            )
            research_round = self._start_network_round(
                index,
                previous_judgement=previous_judgement,
            )
            queue = self._record_network_seed_queue(
                index,
                research_round.round_id,
                seed_urls,
                previous_judgement=previous_judgement,
            )
            round_topic = research_round.hypothesis
            worker_result = await execute_round(
                index=index,
                round_id=research_round.round_id,
                topic=round_topic,
                seed_urls=list(seed_urls),
                previous_judgement=previous_judgement,
                planned_tasks=planned_tasks,
                allow_open_search=active_open_search_plan is not None,
                open_search_plan_id=(
                    active_open_search_plan.plan_id
                    if active_open_search_plan is not None
                    else ""
                ),
                open_search_plan_payload=(
                    active_open_search_plan.to_dict()
                    if active_open_search_plan is not None
                    else None
                ),
            )
            imported = self._import_network_worker_domain(worker_result.domain_path)
            if not imported["new_source_ids"]:
                consecutive_no_new_sources += 1
            else:
                consecutive_no_new_sources = 0
            self._append_domain_trace(
                event_type="network_worker_domain_imported",
                target_type="ResearchRound",
                target_id=research_round.round_id,
                input_refs=[
                    queue.queue_id,
                    str(getattr(worker_result, "run_id", "")),
                    str(getattr(worker_result, "domain_path", "")),
                ],
                output_refs=[
                    *imported["new_source_ids"],
                    *imported["new_evidence_ids"],
                ],
                summary=f"imported network worker domain rows for {research_round.round_id}",
                payload={
                    "source_ids": imported["source_ids"],
                    "evidence_ids": imported["evidence_ids"],
                    "new_source_ids": imported["new_source_ids"],
                    "new_evidence_ids": imported["new_evidence_ids"],
                    "worker_run_dir": str(getattr(worker_result, "run_dir", "")),
                    "artifact_dir": str(getattr(worker_result, "artifact_dir", "")),
                },
            )
            reports = self._network_worker_reports(
                index,
                research_round.round_id,
                queue.selected_lead_ids,
                imported["evidence_ids"],
                worker_result=worker_result,
            )
            research_round.worker_report_ids = [report.report_id for report in reports]
            self.store.upsert_research_round(research_round)
            self._append_domain_trace(
                event_type="worker_reports_recorded",
                target_type="ResearchRound",
                target_id=research_round.round_id,
                input_refs=[*queue.selected_lead_ids, *imported["evidence_ids"]],
                output_refs=list(research_round.worker_report_ids),
                summary=f"network worker reports recorded for {research_round.round_id}",
                payload={
                    "worker_report_ids": list(research_round.worker_report_ids),
                    "network_worker_run_id": str(getattr(worker_result, "run_id", "")),
                },
            )
            judgement = await self._judge_round(
                research_round=research_round,
                reports=reports,
            )
            network_worker_runs.append(
                {
                    "round_id": research_round.round_id,
                    "run_id": str(getattr(worker_result, "run_id", "")),
                    "run_dir": str(getattr(worker_result, "run_dir", "")),
                    "artifact_dir": str(getattr(worker_result, "artifact_dir", "")),
                    "domain_path": str(getattr(worker_result, "domain_path", "")),
                    "trace_event_count": int(
                        getattr(worker_result, "trace_event_count", 0) or 0
                    ),
                    "report_trace_event_count": int(
                        getattr(worker_result, "report_trace_event_count", 0) or 0
                    ),
                    "evidence_ids": list(imported["evidence_ids"]),
                    "new_evidence_ids": list(imported["new_evidence_ids"]),
                    "allow_open_search": active_open_search_plan is not None,
                    "open_search_plan_id": (
                        active_open_search_plan.plan_id
                        if active_open_search_plan is not None
                        else ""
                    ),
                }
            )
            new_strong_evidence_count = self._count_new_strong_evidence(
                imported["new_evidence_ids"]
            )
            next_open_search_plan = self._maybe_create_open_search_plan(
                round_index=index,
                research_round=research_round,
                judgement=judgement,
                new_strong_evidence_count=new_strong_evidence_count,
                consecutive_no_new_sources=consecutive_no_new_sources,
            )
            if next_open_search_plan is not None:
                research_round = ResearchRound(
                    **{
                        **research_round.to_dict(),
                        "status": "judged",
                        "judgement_id": judgement.judgement_id,
                        "next_round_plan": judgement.next_round_plan,
                    }
                )
                self.store.upsert_research_round(research_round)
                self.store.upsert_judgement_report(judgement)
                self.trace.append("judgement")
                round_rows.append(_round_row(research_round, judgement))
                previous_judgement = judgement
                active_open_search_plan = next_open_search_plan
                continue
            decision = evaluate_stop_conditions(
                round_index=index,
                max_rounds=self.max_rounds,
                new_strong_evidence_count=new_strong_evidence_count,
                judgement=judgement,
                consecutive_no_new_sources=consecutive_no_new_sources,
            )
            if decision.should_stop:
                judgement.stop_or_continue = "stop"
                if active_open_search_plan is not None:
                    active_open_search_plan = self._mark_open_search_plan_status(
                        active_open_search_plan,
                        "completed",
                    )
                research_round = ResearchRound(
                    **{
                        **research_round.to_dict(),
                        "status": "stopped",
                        "judgement_id": judgement.judgement_id,
                        "next_round_plan": judgement.next_round_plan,
                        "stop_reason": decision.reason,
                    }
                )
                self.store.upsert_research_round(research_round)
                self.store.upsert_judgement_report(judgement)
                self.trace.append("judgement")
                self.candidate_synthesis = synthesize_candidate_from_judgement(
                    judgement,
                    self.store,
                )
                if self.candidate_synthesis.status == "synthesized":
                    self._append_domain_trace(
                        event_type="candidate_synthesized",
                        target_type="CandidateDemand",
                        target_id=self.candidate_synthesis.candidate_id,
                        input_refs=[
                            judgement.judgement_id,
                            *self.candidate_synthesis.evidence_ids,
                        ],
                        output_refs=[self.candidate_synthesis.candidate_id],
                        summary=(
                            "candidate synthesized from judgement "
                            f"{judgement.judgement_id}"
                        ),
                        decision=self.candidate_synthesis.status,
                        rationale=self.candidate_synthesis.rationale,
                        payload={
                            "open_questions": list(
                                self.candidate_synthesis.open_questions
                            )
                        },
                    )
                self.trace.append("candidate_synthesis")
                round_rows.append(_round_row(research_round, judgement))
                break
            research_round = ResearchRound(
                **{
                    **research_round.to_dict(),
                    "status": "judged",
                    "judgement_id": judgement.judgement_id,
                    "next_round_plan": judgement.next_round_plan,
                }
            )
            self.store.upsert_research_round(research_round)
            self.trace.append("judgement")
            round_rows.append(_round_row(research_round, judgement))
            previous_judgement = judgement
        return {
            "rounds": round_rows,
            "trace": list(self.trace),
            "candidate_synthesis": (
                self.candidate_synthesis.to_dict()
                if self.candidate_synthesis is not None
                else None
            ),
            "network_worker_runs": network_worker_runs,
            "open_search_plans": [
                plan.to_dict() for plan in self.store.open_search_plans.values()
            ],
        }

    async def run_network_open_search_repair_round(
        self,
        *,
        seed_urls: list[str],
        execute_round: Callable[..., Awaitable[Any]],
        trigger_audit_id: str,
        repair_queries: list[str],
        previous_judgement: JudgementReport | None,
    ) -> dict[str, Any] | None:
        next_index = _next_round_index(self.store)
        if next_index > self.max_rounds:
            return None
        queries = _dedupe_nonempty(repair_queries, limit=6)
        if not queries:
            return None
        research_round = self._start_network_round(
            next_index,
            previous_judgement=previous_judgement,
        )
        research_round = replace(
            research_round,
            hypothesis=f"审计返工开放补证：{'；'.join(queries[:3])}",
            updated_at=_now(),
        )
        self.store.upsert_research_round(research_round)
        now = _now()
        plan = OpenSearchPlan(
            plan_id=_stable_id(
                "osp",
                f"{self.run_id}|{research_round.round_id}|{trigger_audit_id}|audit_repair",
            ),
            run_id=self.run_id,
            round_id=research_round.round_id,
            topic=self.topic,
            trigger_judgement_id=f"audit:{trigger_audit_id}",
            trigger_reason="audit_needs_revision",
            queries=queries,
            allowed_result_count=6,
            status="planned",
            created_at=now,
            updated_at=now,
        )
        self.store.upsert_open_search_plan(plan)
        self.trace.append("audit_repair_plan")
        self._append_domain_trace(
            event_type="open_search_plan_created",
            target_type="OpenSearchPlan",
            target_id=plan.plan_id,
            input_refs=[research_round.round_id, trigger_audit_id],
            output_refs=[plan.plan_id],
            summary=f"created audit repair open search plan {plan.plan_id}",
            decision="audit_needs_revision",
            rationale="audit required additional independent evidence",
            payload={
                "queries": list(plan.queries),
                "allowed_result_count": plan.allowed_result_count,
            },
        )
        plan = self._mark_open_search_plan_status(plan, "running")
        queue = self._record_network_seed_queue(
            next_index,
            research_round.round_id,
            seed_urls,
            previous_judgement=previous_judgement,
        )
        worker_result = await execute_round(
            index=next_index,
            round_id=research_round.round_id,
            topic=research_round.hypothesis,
            seed_urls=list(seed_urls),
            previous_judgement=previous_judgement,
            planned_tasks=_audit_repair_planned_tasks(
                trigger_audit_id=trigger_audit_id,
                repair_queries=queries,
            ),
            allow_open_search=True,
            open_search_plan_id=plan.plan_id,
            open_search_plan_payload=plan.to_dict(),
        )
        imported = self._import_network_worker_domain(worker_result.domain_path)
        self._append_domain_trace(
            event_type="network_worker_domain_imported",
            target_type="ResearchRound",
            target_id=research_round.round_id,
            input_refs=[
                queue.queue_id,
                str(getattr(worker_result, "run_id", "")),
                str(getattr(worker_result, "domain_path", "")),
            ],
            output_refs=[
                *imported["new_source_ids"],
                *imported["new_evidence_ids"],
            ],
            summary=f"imported network worker domain rows for {research_round.round_id}",
            payload={
                "source_ids": imported["source_ids"],
                "evidence_ids": imported["evidence_ids"],
                "new_source_ids": imported["new_source_ids"],
                "new_evidence_ids": imported["new_evidence_ids"],
                "worker_run_dir": str(getattr(worker_result, "run_dir", "")),
            },
        )
        reports = self._network_worker_reports(
            next_index,
            research_round.round_id,
            queue.selected_lead_ids,
            imported["evidence_ids"],
            worker_result=worker_result,
        )
        research_round.worker_report_ids = [report.report_id for report in reports]
        self.store.upsert_research_round(research_round)
        self._append_domain_trace(
            event_type="worker_reports_recorded",
            target_type="ResearchRound",
            target_id=research_round.round_id,
            input_refs=[*queue.selected_lead_ids, *imported["evidence_ids"]],
            output_refs=list(research_round.worker_report_ids),
            summary=f"network worker reports recorded for {research_round.round_id}",
            payload={
                "worker_report_ids": list(research_round.worker_report_ids),
                "network_worker_run_id": str(getattr(worker_result, "run_id", "")),
            },
        )
        judgement = await self._judge_round(
            research_round=research_round,
            reports=reports,
        )
        plan = self._mark_open_search_plan_status(plan, "completed")
        research_round = ResearchRound(
            **{
                **research_round.to_dict(),
                "status": "stopped" if judgement.stop_or_continue == "stop" else "judged",
                "judgement_id": judgement.judgement_id,
                "next_round_plan": judgement.next_round_plan,
                "stop_reason": (
                    "audit_repair_judge_stop"
                    if judgement.stop_or_continue == "stop"
                    else None
                ),
            }
        )
        self.store.upsert_research_round(research_round)
        self.store.upsert_judgement_report(judgement)
        self.trace.append("judgement")
        if judgement.stop_or_continue == "stop":
            self.candidate_synthesis = synthesize_candidate_from_judgement(
                judgement,
                self.store,
            )
            if self.candidate_synthesis.status == "synthesized":
                self._append_domain_trace(
                    event_type="candidate_synthesized",
                    target_type="CandidateDemand",
                    target_id=self.candidate_synthesis.candidate_id,
                    input_refs=[
                        judgement.judgement_id,
                        *self.candidate_synthesis.evidence_ids,
                    ],
                    output_refs=[self.candidate_synthesis.candidate_id],
                    summary=(
                        "candidate synthesized from audit repair judgement "
                        f"{judgement.judgement_id}"
                    ),
                    decision=self.candidate_synthesis.status,
                    rationale=self.candidate_synthesis.rationale,
                    payload={
                        "open_questions": list(
                            self.candidate_synthesis.open_questions
                        )
                    },
                )
            self.trace.append("candidate_synthesis")
        return {
            "round": _round_row(research_round, judgement),
            "network_worker_run": {
                "round_id": research_round.round_id,
                "run_id": str(getattr(worker_result, "run_id", "")),
                "run_dir": str(getattr(worker_result, "run_dir", "")),
                "domain_path": str(getattr(worker_result, "domain_path", "")),
                "trace_event_count": int(
                    getattr(worker_result, "trace_event_count", 0) or 0
                ),
                "report_trace_event_count": int(
                    getattr(worker_result, "report_trace_event_count", 0) or 0
                ),
                "evidence_ids": list(imported["evidence_ids"]),
                "new_evidence_ids": list(imported["new_evidence_ids"]),
                "allow_open_search": True,
                "open_search_plan_id": plan.plan_id,
            },
            "candidate_synthesis": (
                self.candidate_synthesis.to_dict()
                if self.candidate_synthesis is not None
                else None
            ),
            "open_search_plan": plan.to_dict(),
        }

    async def _judge_round(
        self,
        *,
        research_round: ResearchRound,
        reports: list[WorkerReport],
    ) -> JudgementReport:
        if self.judge_provider_factory is None:
            raise RuntimeError("judge_provider_factory is required for model judge")
        judgement = await run_judge_agent_for_round(
            round_id=research_round.round_id,
            worker_reports=reports,
            domain_store=self.store,
            provider_factory=self.judge_provider_factory,
            run_id=self.run_id,
            sessions_dir=self.judge_sessions_dir,
        )
        judgement = self._validate_or_repair_judgement_plan(judgement)
        self.store.upsert_judgement_report(judgement)
        self._append_domain_trace(
            event_type="judgement_consumed_by_controller",
            target_type="JudgementReport",
            target_id=judgement.judgement_id,
            input_refs=[
                *research_round.worker_report_ids,
                *[
                    evidence_id
                    for report in reports
                    for evidence_id in report.evidence_refs
                ],
                *[
                    lead_id
                    for report in reports
                    for lead_id in report.lead_refs
                ],
            ],
            output_refs=[judgement.judgement_id],
            summary=f"controller consumed judgement {judgement.judgement_id}",
            decision=judgement.stop_or_continue,
            rationale=judgement.rationale,
            payload={"next_round_plan": judgement.next_round_plan},
        )
        return judgement

    def _should_trigger_open_search(
        self,
        *,
        round_index: int,
        judgement: JudgementReport,
        new_strong_evidence_count: int,
        consecutive_no_new_sources: int,
        budget_exhausted: bool = False,
    ) -> OpenSearchTriggerDecision:
        if round_index < 1:
            return OpenSearchTriggerDecision(False, "whitelist_round_required")
        if round_index >= self.max_rounds:
            return OpenSearchTriggerDecision(False, "max_rounds")
        if budget_exhausted:
            return OpenSearchTriggerDecision(False, "budget_exhausted")
        tasks = self._open_search_tasks_from_judgement(judgement)
        if not tasks:
            return OpenSearchTriggerDecision(False, "judge_did_not_request_open_search")
        if not any(self._task_marks_whitelist_exhausted(task) for task in tasks):
            return OpenSearchTriggerDecision(False, "whitelist_not_exhausted")
        return OpenSearchTriggerDecision(True, "judge_gap_after_whitelist_exhaustion")

    def _maybe_create_open_search_plan(
        self,
        *,
        round_index: int,
        research_round: ResearchRound,
        judgement: JudgementReport,
        new_strong_evidence_count: int,
        consecutive_no_new_sources: int,
        budget_exhausted: bool = False,
    ) -> OpenSearchPlan | None:
        decision = self._should_trigger_open_search(
            round_index=round_index,
            judgement=judgement,
            new_strong_evidence_count=new_strong_evidence_count,
            consecutive_no_new_sources=consecutive_no_new_sources,
            budget_exhausted=budget_exhausted,
        )
        if not decision.should_trigger:
            return None
        existing = self._open_search_plan_for_judgement(judgement.judgement_id)
        if existing is not None:
            return existing
        now = _now()
        plan = OpenSearchPlan(
            plan_id=_stable_id(
                "osp",
                f"{self.run_id}|{research_round.round_id}|{judgement.judgement_id}",
            ),
            run_id=self.run_id,
            round_id=research_round.round_id,
            topic=self.topic,
            trigger_judgement_id=judgement.judgement_id,
            trigger_reason=decision.reason,
            queries=self._open_search_queries_from_judgement(judgement),
            allowed_result_count=6,
            status="planned",
            created_at=now,
            updated_at=now,
        )
        self.store.upsert_open_search_plan(plan)
        self.trace.append("open_search_plan")
        self._append_domain_trace(
            event_type="open_search_plan_created",
            target_type="OpenSearchPlan",
            target_id=plan.plan_id,
            input_refs=[research_round.round_id, judgement.judgement_id],
            output_refs=[plan.plan_id],
            summary=f"created open search plan {plan.plan_id}",
            decision=decision.reason,
            rationale=judgement.rationale,
            payload={
                "queries": list(plan.queries),
                "allowed_result_count": plan.allowed_result_count,
            },
        )
        return plan

    def _open_search_plan_for_judgement(
        self,
        judgement_id: str,
    ) -> OpenSearchPlan | None:
        for plan in self.store.open_search_plans.values():
            if plan.trigger_judgement_id == judgement_id:
                return plan
        return None

    def _mark_open_search_plan_status(
        self,
        plan: OpenSearchPlan,
        status: str,
    ) -> OpenSearchPlan:
        if plan.status == status:
            return plan
        updated = replace(plan, status=status, updated_at=_now())
        self.store.upsert_open_search_plan(updated)
        return updated

    def _count_new_strong_evidence(self, evidence_ids: list[str]) -> int:
        count = 0
        for evidence_id in evidence_ids:
            if not evidence_has_strong_or_direct_support(self.store, evidence_id):
                continue
            evidence = self.store.evidence.get(evidence_id)
            if evidence is None:
                continue
            source = self.store.sources.get(evidence.source_id)
            if source is not None and source.open_source_lead_id:
                quality_id = evidence.source_quality_assessment_id or ""
                quality = self.store.source_quality_assessments.get(quality_id)
                if quality is None or quality.quality_level not in {"trusted", "usable"}:
                    continue
                if quality.lead_id != source.open_source_lead_id:
                    continue
                if evidence.source_location not in quality.body_location_refs:
                    continue
            count += 1
        return count

    def _open_search_tasks_from_judgement(
        self,
        judgement: JudgementReport,
    ) -> list[dict[str, Any]]:
        return routed_open_search_tasks_from_judgement(judgement, topic=self.topic)

    def _task_marks_whitelist_exhausted(self, task: dict[str, Any]) -> bool:
        if task.get("source_scope") == "open_web_after_whitelist_exhausted":
            return True
        completion_check = str(task.get("completion_check", ""))
        return "白名单" in completion_check and (
            "耗尽" in completion_check or "无新增" in completion_check
        )

    def _open_search_queries_from_judgement(
        self,
        judgement: JudgementReport,
    ) -> list[str]:
        return routed_open_search_queries_from_judgement(
            judgement,
            fallback_topic=self.topic,
            limit=6,
        )

    def _validate_or_repair_judgement_plan(
        self,
        judgement: JudgementReport,
    ) -> JudgementReport:
        assessment = assess_next_round_plan(judgement.next_round_plan)
        if assessment.is_valid:
            self._append_domain_trace(
                event_type="judge_plan_validated",
                target_type="JudgementReport",
                target_id=judgement.judgement_id,
                input_refs=[judgement.judgement_id],
                output_refs=[judgement.judgement_id],
                summary=f"validated judge next_round_plan {judgement.judgement_id}",
                decision="valid",
                payload={
                    "controller_task_count": len(assessment.controller_tasks),
                    "warning_count": len(assessment.warnings),
                },
            )
            self.trace.append("judge_plan_validated")
            return judgement
        repaired = build_repaired_next_round_plan(
            judgement.next_round_plan,
            topic=self.topic,
            round_id=judgement.round_id,
        )
        repaired_assessment = assess_next_round_plan(repaired)
        judgement.next_round_plan = repaired
        self.store.upsert_judgement_report(judgement)
        if assessment.brief_mismatch_task_ids:
            self._append_domain_trace(
                event_type="judge_plan_brief_mismatch",
                target_type="JudgementReport",
                target_id=judgement.judgement_id,
                input_refs=[judgement.judgement_id],
                output_refs=[judgement.judgement_id],
                summary=f"judge worker_brief mismatch repaired for {judgement.judgement_id}",
                decision="repaired",
                payload={
                    "task_ids": list(assessment.brief_mismatch_task_ids),
                    "errors": list(assessment.errors),
                },
            )
            self.trace.append("judge_plan_brief_mismatch")
        event_type = (
            "judge_plan_repaired"
            if repaired_assessment.is_valid
            else "judge_plan_needs_revision"
        )
        self._append_domain_trace(
            event_type=event_type,
            target_type="JudgementReport",
            target_id=judgement.judgement_id,
            input_refs=[judgement.judgement_id],
            output_refs=[judgement.judgement_id],
            summary=f"{event_type} {judgement.judgement_id}",
            decision="valid" if repaired_assessment.is_valid else "invalid",
            payload={
                "original_errors": list(assessment.errors),
                "repair_errors": list(repaired_assessment.errors),
                "controller_task_count": len(repaired_assessment.controller_tasks),
            },
        )
        self.trace.append(event_type)
        return judgement

    def _plan_worker_assignments(
        self,
        previous_judgement: JudgementReport | None,
        *,
        next_round_id: str,
    ) -> list[dict[str, Any]]:
        if previous_judgement is None:
            return []
        assignments = worker_assignments_from_judgement(
            previous_judgement,
            topic=self.topic,
        )
        self._append_domain_trace(
            event_type="worker_assignments_planned",
            target_type="JudgementReport",
            target_id=previous_judgement.judgement_id,
            input_refs=[previous_judgement.judgement_id],
            output_refs=[
                str(task.get("task_id", ""))
                for task in assignments
                if str(task.get("task_id", "")).strip()
            ],
            summary=(
                "planned worker assignments from judgement "
                f"{previous_judgement.judgement_id}"
            ),
            payload={
                "next_round_id": next_round_id,
                "assignment_count": len(assignments),
                "assignments": [
                    {
                        "task_id": str(task.get("task_id", "")),
                        "routing_hint": str(task.get("routing_hint", "")),
                        "source_scope": str(task.get("source_scope", "")),
                        "input_refs": dict(task.get("input_refs", {}))
                        if isinstance(task.get("input_refs", {}), dict)
                        else {},
                        "query_revisions": list(task.get("query_revisions", []))
                        if isinstance(task.get("query_revisions", []), list)
                        else [],
                    }
                    for task in assignments
                ],
            },
        )
        self.trace.append("worker_assignments_planned")
        return assignments

    def _run_fake_round(
        self,
        index: int,
        *,
        previous_judgement: JudgementReport | None,
        active_open_search_plan: OpenSearchPlan | None,
    ) -> tuple[ResearchRound, list[WorkerReport], int, int]:
        round_id = f"round-{index}"
        self._plan_worker_assignments(
            previous_judgement,
            next_round_id=round_id,
        )
        previous_plan = (
            dict(previous_judgement.next_round_plan)
            if previous_judgement is not None
            else {}
        )
        plan_query = _first_plan_query(previous_plan)
        hypothesis = (
            f"第 {index} 轮按上一轮 next_round_plan 追问：{plan_query}"
            if plan_query
            else f"第 {index} 轮验证“{self.topic}”的能力缺口证据。"
        )
        research_round = ResearchRound(
            round_id=round_id,
            run_id=self.run_id,
            index=index,
            topic=self.topic,
            hypothesis=hypothesis,
            source_strategy_id=self.strategy.strategy_id,
            worker_report_ids=[],
            judgement_id=None,
            next_round_plan={},
            stop_reason=None,
            status="running",
            created_at=_now(),
            updated_at=_now(),
        )
        self.store.upsert_research_round(research_round)
        self.trace.append("research_round")
        self._append_domain_trace(
            event_type="research_round_started",
            target_type="ResearchRound",
            target_id=round_id,
            input_refs=[
                self.strategy.strategy_id,
                *(
                    [previous_judgement.judgement_id]
                    if previous_judgement is not None
                    else []
                ),
            ],
            output_refs=[round_id],
            summary=hypothesis,
            payload={"next_round_plan": previous_plan},
        )
        selected_lead_id = f"lead-{index}-selected"
        skipped_lead_id = f"lead-{index}-skipped"
        failed_lead_id = f"lead-{index}-failed"
        source = next(
            (
                item
                for item in self.strategy.selected_sources
                if item.source_tier == "A"
            ),
            self.strategy.selected_sources[0],
        )
        lead = ResearchLead(
            lead_id=selected_lead_id,
            round_id=round_id,
            source_name=source.source_name,
            source_tier=source.source_tier,
            url=source.entry_urls[0],
            title=f"{self.topic} round {index}",
            snippet=(
                f"{plan_query}；低空无人机威胁压缩预警时间，需要多源探测和快速告警。"
                if plan_query
                else "低空无人机威胁压缩预警时间，需要多源探测和快速告警。"
            ),
            page_type="article",
            download_kind="none",
            relevance_score=0.9,
            importance_score=0.8,
            credibility_score=0.9,
            status="read",
            selection_reason=(
                f"fake topic match from previous next_round_plan: {plan_query}"
                if plan_query
                else "fake topic match"
            ),
            skip_reason="",
            artifact_refs=[],
            created_at=_now(),
            updated_at=_now(),
        )
        skipped = ResearchLead(
            **{
                **lead.to_dict(),
                "lead_id": skipped_lead_id,
                "url": "https://outside.example/skipped",
                "status": "skipped",
                "selection_reason": "",
                "skip_reason": "outside source whitelist",
            }
        )
        failed = ResearchLead(
            **{
                **lead.to_dict(),
                "lead_id": failed_lead_id,
                "url": f"{source.entry_urls[0].rstrip('/')}/failed",
                "status": "failed",
                "selection_reason": "",
                "skip_reason": "fetch failed",
            }
        )
        for item in [lead, skipped, failed]:
            self.store.upsert_research_lead(item)
        self.store.upsert_reading_queue(
            ReadingQueue(
                queue_id=f"queue-{index}",
                round_id=round_id,
                topic=self.topic,
                lead_ids=[selected_lead_id, skipped_lead_id, failed_lead_id],
                selected_lead_ids=[selected_lead_id],
                skipped_lead_ids=[skipped_lead_id],
                failed_lead_ids=[failed_lead_id],
                budget_snapshot={
                    "round": index,
                    "planned_from_judgement_id": (
                        previous_judgement.judgement_id
                        if previous_judgement is not None
                        else ""
                    ),
                    "next_round_plan": previous_plan,
                },
                created_at=_now(),
                updated_at=_now(),
            )
        )
        queue_id = f"queue-{index}"
        self._append_domain_trace(
            event_type="research_leads_recorded",
            target_type="ReadingQueue",
            target_id=queue_id,
            input_refs=[round_id, source.entry_urls[0]],
            output_refs=[queue_id, selected_lead_id, skipped_lead_id, failed_lead_id],
            summary=f"recorded reading queue {queue_id}",
            payload={
                "selected_lead_ids": [selected_lead_id],
                "skipped_lead_ids": [skipped_lead_id],
                "failed_lead_ids": [failed_lead_id],
            },
        )
        if active_open_search_plan is None:
            evidence_ids: list[str] = []
            new_source_count = 0
        else:
            evidence_ids = self._create_fake_open_search_evidence(
                index,
                active_open_search_plan,
                selected_lead_id,
            )
            new_source_count = 1
        planned_finding = plan_query or "需要多源探测和快速告警"
        first_round_open_question = "缺少白名单外公开正文交叉材料"
        reports = [
            WorkerReport(
                agent_run_id=f"agent-{index}-a",
                report_id=f"agent-{index}-a",
                role="reader",
                status="completed",
                partial_findings=[
                    "白名单入口未返回足够正文证据",
                    planned_finding,
                ],
                new_evidence_cards=evidence_ids[:1],
                evidence_refs=evidence_ids[:1],
                lead_refs=[selected_lead_id],
                open_questions=[
                    first_round_open_question
                ] if not evidence_ids else [],
                risk_or_conflict=[
                    "白名单 route/query 无新增强证据"
                ] if not evidence_ids else [],
                need_more_sources=not bool(evidence_ids),
            ),
            WorkerReport(
                agent_run_id=f"agent-{index}-b",
                report_id=f"agent-{index}-b",
                role="reader",
                status="completed",
                partial_findings=[
                    planned_finding,
                    "不同来源材料需要继续交叉验证能力缺口边界",
                ],
                new_evidence_cards=evidence_ids[1:2],
                evidence_refs=evidence_ids[1:2],
                lead_refs=[selected_lead_id],
                open_questions=[
                    first_round_open_question
                ] if not evidence_ids else [],
                risk_or_conflict=[
                    "白名单 route/query 无新增强证据"
                ] if not evidence_ids else [],
                need_more_sources=not bool(evidence_ids),
            ),
        ]
        research_round.worker_report_ids = [report.report_id for report in reports]
        self.store.upsert_research_round(research_round)
        self._append_domain_trace(
            event_type="worker_reports_recorded",
            target_type="ResearchRound",
            target_id=round_id,
            input_refs=[selected_lead_id, *evidence_ids],
            output_refs=list(research_round.worker_report_ids),
            summary=f"worker reports recorded for {round_id}",
            payload={
                "worker_report_ids": list(research_round.worker_report_ids),
                "planned_from_next_round_plan": bool(previous_plan),
            },
        )
        return (
            research_round,
            reports,
            self._count_new_strong_evidence(evidence_ids),
            new_source_count,
        )

    def _start_network_round(
        self,
        index: int,
        *,
        previous_judgement: JudgementReport | None,
    ) -> ResearchRound:
        round_id = f"round-{index}"
        previous_plan = (
            dict(previous_judgement.next_round_plan)
            if previous_judgement is not None
            else {}
        )
        plan_query = _first_plan_query(previous_plan)
        hypothesis = (
            f"第 {index} 轮按上一轮 next_round_plan 追问：{plan_query}"
            if plan_query
            else f"第 {index} 轮验证“{self.topic}”的能力缺口证据。"
        )
        research_round = ResearchRound(
            round_id=round_id,
            run_id=self.run_id,
            index=index,
            topic=self.topic,
            hypothesis=hypothesis,
            source_strategy_id=self.strategy.strategy_id,
            worker_report_ids=[],
            judgement_id=None,
            next_round_plan={},
            stop_reason=None,
            status="running",
            created_at=_now(),
            updated_at=_now(),
        )
        self.store.upsert_research_round(research_round)
        self.trace.append("research_round")
        self._append_domain_trace(
            event_type="research_round_started",
            target_type="ResearchRound",
            target_id=round_id,
            input_refs=[
                self.strategy.strategy_id,
                *(
                    [previous_judgement.judgement_id]
                    if previous_judgement is not None
                    else []
                ),
            ],
            output_refs=[round_id],
            summary=hypothesis,
            payload={"next_round_plan": previous_plan},
        )
        return research_round

    def _record_network_seed_queue(
        self,
        index: int,
        round_id: str,
        seed_urls: list[str],
        *,
        previous_judgement: JudgementReport | None,
    ) -> ReadingQueue:
        leads: list[ResearchLead] = []
        for lead_index, url in enumerate(seed_urls, start=1):
            entry = self.registry.match(url)
            source_name = entry.source_name if entry is not None else ""
            source_tier = entry.source_tier if entry is not None else ""
            leads.append(
                ResearchLead(
                    lead_id=f"lead-{index}-{lead_index}-selected",
                    round_id=round_id,
                    source_name=source_name,
                    source_tier=source_tier,
                    url=url,
                    title=f"{source_name or 'source'} seed entry",
                    snippet=f"whitelisted seed selected for topic: {self.topic}",
                    page_type="site_home",
                    download_kind="none",
                    relevance_score=0.7,
                    importance_score=0.7,
                    credibility_score=0.8,
                    status="selected",
                    selection_reason="source strategy seed entry",
                    skip_reason="",
                    artifact_refs=[],
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
        for lead in leads:
            self.store.upsert_research_lead(lead)
        queue = ReadingQueue(
            queue_id=f"queue-{index}",
            round_id=round_id,
            topic=self.topic,
            lead_ids=[lead.lead_id for lead in leads],
            selected_lead_ids=[lead.lead_id for lead in leads],
            skipped_lead_ids=[],
            failed_lead_ids=[],
            budget_snapshot={
                "round": index,
                "planned_from_judgement_id": (
                    previous_judgement.judgement_id
                    if previous_judgement is not None
                    else ""
                ),
                "next_round_plan": (
                    dict(previous_judgement.next_round_plan)
                    if previous_judgement is not None
                    else {}
                ),
            },
            created_at=_now(),
            updated_at=_now(),
        )
        self.store.upsert_reading_queue(queue)
        self._append_domain_trace(
            event_type="research_leads_recorded",
            target_type="ReadingQueue",
            target_id=queue.queue_id,
            input_refs=[round_id, *seed_urls],
            output_refs=[queue.queue_id, *queue.selected_lead_ids],
            summary=f"recorded reading queue {queue.queue_id}",
            payload={
                "selected_lead_ids": list(queue.selected_lead_ids),
                "skipped_lead_ids": [],
                "failed_lead_ids": [],
            },
        )
        return queue

    def _import_network_worker_domain(self, domain_path: Any) -> dict[str, list[str]]:
        before_sources = set(self.store.sources)
        before_evidence = set(self.store.evidence)
        before_open_search_plans = set(self.store.open_search_plans)
        before_open_source_leads = set(self.store.open_source_leads)
        before_open_source_body_artifacts = set(self.store.open_source_body_artifacts)
        before_source_quality_assessments = set(self.store.source_quality_assessments)
        imported_store = DomainStore.load_jsonl(domain_path)
        for plan in imported_store.open_search_plans.values():
            self.store.upsert_open_search_plan(plan)
        for lead in imported_store.open_source_leads.values():
            self.store.upsert_open_source_lead(lead)
        for body in imported_store.open_source_body_artifacts.values():
            self.store.upsert_open_source_body_artifact(body)
        for assessment in imported_store.source_quality_assessments.values():
            self.store.upsert_source_quality_assessment(assessment)
        for source in imported_store.sources.values():
            self.store.upsert_source(source)
        for evidence in imported_store.evidence.values():
            if evidence.source_id and evidence.source_id not in self.store.sources:
                continue
            self.store.upsert_evidence(evidence)
        source_ids = list(imported_store.sources)
        evidence_ids = [
            evidence_id
            for evidence_id in imported_store.evidence
            if evidence_id in self.store.evidence
        ]
        return {
            "source_ids": source_ids,
            "evidence_ids": evidence_ids,
            "new_source_ids": [
                source_id
                for source_id in source_ids
                if source_id not in before_sources
            ],
            "new_evidence_ids": [
                evidence_id
                for evidence_id in evidence_ids
                if evidence_id not in before_evidence
            ],
            "open_search_plan_ids": list(imported_store.open_search_plans),
            "open_source_lead_ids": list(imported_store.open_source_leads),
            "source_quality_assessment_ids": list(
                imported_store.source_quality_assessments
            ),
            "new_open_search_plan_ids": [
                plan_id
                for plan_id in imported_store.open_search_plans
                if plan_id not in before_open_search_plans
            ],
            "new_open_source_lead_ids": [
                lead_id
                for lead_id in imported_store.open_source_leads
                if lead_id not in before_open_source_leads
            ],
            "new_open_source_body_artifact_ids": [
                body_id
                for body_id in imported_store.open_source_body_artifacts
                if body_id not in before_open_source_body_artifacts
            ],
            "new_source_quality_assessment_ids": [
                assessment_id
                for assessment_id in imported_store.source_quality_assessments
                if assessment_id not in before_source_quality_assessments
            ],
        }

    def _network_worker_reports(
        self,
        index: int,
        round_id: str,
        lead_ids: list[str],
        evidence_ids: list[str],
        *,
        worker_result: Any,
    ) -> list[WorkerReport]:
        consensus = _network_consensus_text(self.topic, self.store, evidence_ids)
        parsed = parse_worker_text(str(getattr(worker_result, "final_text", "") or ""))
        default_open_question = "继续补充白名单正文材料交叉验证能力缺口"
        worker_error = str(getattr(worker_result, "error", "") or "")
        has_strong_evidence = self._count_new_strong_evidence(evidence_ids) > 0
        needs_more_sources = (
            bool(worker_error)
            or bool(parsed["need_more_sources"])
            or not has_strong_evidence
        )
        risks: list[str] = []
        if needs_more_sources:
            risks.append("部分真实网络证据可能来自入口页或访问状态页，需继续读取正文材料")
        risks = _dedupe_nonempty([*list(parsed["risks"]), *risks], limit=12)
        if worker_error:
            risks.append(worker_error[:500])
        parsed_findings = _dedupe_nonempty(list(parsed["findings"]), limit=12)
        open_questions = _dedupe_nonempty(
            [
                *list(parsed["open_questions"]),
                *list(parsed["remaining_gaps"]),
                *(
                    [default_open_question]
                    if needs_more_sources and not parsed["remaining_gaps"]
                    else []
                ),
            ],
            limit=12,
        )
        common = {
            "status": "failed" if worker_error and not evidence_ids else "completed",
            "partial_findings": parsed_findings or [consensus],
            "new_evidence_cards": list(evidence_ids),
            "evidence_refs": list(evidence_ids),
            "lead_refs": list(lead_ids),
            "open_questions": open_questions if needs_more_sources else [],
            "need_more_sources": needs_more_sources,
            "risk_or_conflict": risks,
            "usage": {
                "network_worker_run_id": str(getattr(worker_result, "run_id", "")),
                "network_trace_event_count": int(
                    getattr(worker_result, "trace_event_count", 0) or 0
                ),
            },
            "session_path": str(getattr(worker_result, "run_dir", "")),
            "error": worker_error,
            "evidence_ready_for_judge": parsed["evidence_ready_for_judge"],
            "stop_reason": str(parsed["stop_reason"]),
            "remaining_gaps": list(parsed["remaining_gaps"]),
            "next_round_suggestions": list(parsed["suggested_next_routes"]),
        }
        return [
            WorkerReport(
                agent_run_id=f"agent-{index}-network-reader",
                report_id=f"agent-{index}-network-reader",
                role="reader",
                task_brief=f"network worker evidence import for {round_id}",
                **common,
            ),
            WorkerReport(
                agent_run_id=f"agent-{index}-network-crosscheck",
                report_id=f"agent-{index}-network-crosscheck",
                role="debater",
                task_brief=f"cross-check imported network evidence for {round_id}",
                **common,
            ),
        ]

    def _create_fake_evidence(
        self,
        index: int,
        source: Any,
        lead_id: str,
    ) -> list[str]:
        source_id = f"src-fake-{index}"
        self.store.upsert_source(
            SourceRecord(
                source_id=source_id,
                title=f"{self.topic} fake source {index}",
                source_name=source.source_name,
                source_tier=source.source_tier,
                source_type=source.source_type,
                publish_time=_now(),
                url_or_path=source.entry_urls[0],
                summary_text="fake autonomous research source",
                summary_source="fake",
                collection_decision="use_as_evidence",
                author_or_org=None,
                is_repost=False,
                original_source=None,
                institutional_stance=None,
                created_at=_now(),
                updated_at=_now(),
            )
        )
        self._append_domain_trace(
            event_type="source_seen",
            target_type="SourceRecord",
            target_id=source_id,
            input_refs=[lead_id],
            output_refs=[source_id],
            summary=f"source seen {source_id}",
        )
        evidence_ids = [f"ev-round-{index}-a", f"ev-round-{index}-b"]
        for evidence_id in evidence_ids:
            self.store.upsert_evidence(
                EvidenceCard(
                    evidence_id=evidence_id,
                    source_id=source_id,
                    claim="需要多源探测和快速告警",
                    evidence_summary="fake worker found low-altitude warning gaps.",
                    excerpt="低空无人机威胁压缩预警时间，需要多源探测和快速告警。",
                    source_location=f"text:fake{index}#para:0",
                    evidence_assessment="strong",
                    created_by="fake-loop",
                    created_at=_now(),
                )
            )
            self._append_domain_trace(
                event_type="evidence_created",
                target_type="EvidenceCard",
                target_id=evidence_id,
                input_refs=[source_id, lead_id],
                output_refs=[evidence_id],
                summary=f"evidence created {evidence_id}",
                payload={"round": index},
            )
        return evidence_ids

    def _create_fake_open_search_evidence(
        self,
        index: int,
        plan: OpenSearchPlan,
        lead_ref: str,
    ) -> list[str]:
        lead_id = f"osl-fake-{index}"
        body_id = f"osb-fake-{index}"
        assessment_id = f"qa-fake-{index}"
        source_id = f"src-open-fake-{index}"
        url = f"https://open.example.test/research/{_stable_id('topic', self.topic)}"
        title = f"{self.topic} open web synthesis"
        lead = OpenSourceLead(
            lead_id=lead_id,
            plan_id=plan.plan_id,
            run_id=self.run_id,
            round_id=f"round-{index}",
            topic=self.topic,
            url=url,
            domain="open.example.test",
            title=title,
            snippet=f"公开正文讨论“{self.topic}”相关能力缺口。",
            source_name_guess="Open Example",
            search_query=plan.queries[0] if plan.queries else self.topic,
            source_scope="open_web",
            quality_status="pending",
            created_at=_now(),
            updated_at=_now(),
        )
        self.store.upsert_open_source_lead(lead)
        self._append_domain_trace(
            event_type="open_search_results_scoped",
            target_type="OpenSearchPlan",
            target_id=plan.plan_id,
            input_refs=[plan.plan_id],
            output_refs=[lead_id],
            summary=f"scoped open search result {lead_id}",
            payload={"query": lead.search_query, "url": url},
        )
        self._append_domain_trace(
            event_type="open_source_lead_recorded",
            target_type="OpenSourceLead",
            target_id=lead_id,
            input_refs=[plan.plan_id],
            output_refs=[lead_id],
            summary=f"recorded open source lead {lead_id}",
        )
        body_prefix = f"text:open-fake-{index}#"
        body = OpenSourceBodyArtifact(
            body_id=body_id,
            lead_id=lead_id,
            plan_id=plan.plan_id,
            url=url,
            final_url=url,
            content_type="text/html",
            artifact_ref=f"html:open-fake-{index}",
            simplified_ref=f"text:open-fake-{index}",
            body_location_prefix=body_prefix,
            fetched_by="fake-loop",
            created_at=_now(),
        )
        self.store.upsert_open_source_body_artifact(body)
        self._append_domain_trace(
            event_type="open_source_body_fetched",
            target_type="OpenSourceBodyArtifact",
            target_id=body_id,
            input_refs=[lead_id, plan.plan_id],
            output_refs=[body_id, body.simplified_ref],
            summary=f"fetched open source body {body_id}",
        )
        assessment = SourceQualityAssessment(
            assessment_id=assessment_id,
            lead_id=lead_id,
            url=url,
            domain="open.example.test",
            basis_artifact_refs=[body.simplified_ref],
            body_location_refs=[f"{body_prefix}para:0", f"{body_prefix}para:1"],
            read_document_ref=body.simplified_ref,
            source_identity="Open Example",
            publisher_or_org="Open Example",
            author="",
            publish_time=_now().date().isoformat(),
            is_original_source=True,
            citation_or_reference_signal="public article body",
            content_type="article",
            quality_level="usable",
            risk_flags=[],
            reason="fake fixture: body artifact and publisher identity are bound to lead",
            created_by="fake-loop",
            created_at=_now(),
        )
        self.store.upsert_source_quality_assessment(assessment)
        self._append_domain_trace(
            event_type="source_quality_assessed",
            target_type="SourceQualityAssessment",
            target_id=assessment_id,
            input_refs=[lead_id, body_id, body.simplified_ref],
            output_refs=[assessment_id],
            summary=f"assessed open source quality {assessment_id}",
            decision=assessment.quality_level,
            rationale=assessment.reason,
        )
        self.store.upsert_source(
            SourceRecord(
                source_id=source_id,
                title=title,
                source_name="Open Example",
                source_tier="B",
                source_type="open_web",
                publish_time=_now(),
                url_or_path=url,
                summary_text=f"公开正文支持“{self.topic}”需要继续核验的能力缺口。",
                summary_source="fake",
                collection_decision="use_as_evidence",
                author_or_org="Open Example",
                is_repost=False,
                original_source=None,
                institutional_stance=None,
                created_at=_now(),
                updated_at=_now(),
                open_source_lead_id=lead_id,
            )
        )
        self._append_domain_trace(
            event_type="source_seen",
            target_type="SourceRecord",
            target_id=source_id,
            input_refs=[lead_id, assessment_id],
            output_refs=[source_id],
            summary=f"source seen {source_id}",
        )
        evidence_ids = [f"ev-open-round-{index}-a", f"ev-open-round-{index}-b"]
        for offset, evidence_id in enumerate(evidence_ids):
            location = f"{body_prefix}para:{offset}"
            self.store.upsert_evidence(
                EvidenceCard(
                    evidence_id=evidence_id,
                    source_id=source_id,
                    claim=f"{self.topic}存在需要补强的能力缺口",
                    evidence_summary=(
                        "fake open-web body provides a usable cross-source "
                        "signal for candidate synthesis."
                    ),
                    excerpt=f"公开正文第 {offset + 1} 段讨论{self.topic}的能力缺口。",
                    source_location=location,
                    evidence_assessment="strong",
                    created_by="fake-loop",
                    created_at=_now(),
                    source_quality_assessment_id=assessment_id,
                )
            )
            self._append_domain_trace(
                event_type="evidence_created",
                target_type="EvidenceCard",
                target_id=evidence_id,
                input_refs=[source_id, lead_id, assessment_id, lead_ref],
                output_refs=[evidence_id],
                summary=f"evidence created {evidence_id}",
                payload={"round": index, "open_search_plan_id": plan.plan_id},
            )
        return evidence_ids

    def _append_domain_trace(
        self,
        *,
        event_type: str,
        target_type: str,
        target_id: str,
        summary: str,
        input_refs: list[str] | None = None,
        output_refs: list[str] | None = None,
        decision: str | None = None,
        rationale: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> DomainTraceEvent:
        return self.store.append_trace(
            DomainTraceEvent(
                domain_trace_id=f"dt-{uuid4().hex}",
                trace_id="autonomous-research",
                event_type=event_type,
                actor="research_loop",
                target_type=target_type,
                target_id=target_id,
                input_refs=list(input_refs or []),
                output_refs=list(output_refs or []),
                summary=summary,
                decision=decision,
                rationale=rationale,
                model=None,
                prompt_id=None,
                tool_refs=[],
                runtime_event_id=None,
                created_at=_now(),
                payload=dict(payload or {}),
            )
        )


def _round_row(round_obj: ResearchRound, judgement: JudgementReport) -> dict[str, Any]:
    return {
        **round_obj.to_dict(),
        "judgement": judgement.to_dict(),
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _next_round_index(store: DomainStore) -> int:
    if not store.research_rounds:
        return 1
    return max(round_obj.index for round_obj in store.research_rounds.values()) + 1


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _query_revisions_from_task(task: dict[str, Any]) -> list[str]:
    value = task.get("query_revisions", [])
    if not isinstance(value, list):
        return _string_list(value)
    rows: list[str] = []
    for item in value:
        if isinstance(item, dict):
            rows.extend(_string_list(item.get("query")))
        else:
            rows.extend(_string_list(item))
    return rows


def _dedupe_nonempty(values: list[str], *, limit: int) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _first_plan_query(plan: dict[str, Any]) -> str:
    if plan.get("plan_version") != 1:
        return ""
    repaired = build_repaired_next_round_plan(plan)
    tasks = repaired.get("controller_tasks", [])
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            for query in _query_revisions_from_task(task):
                if query:
                    return query
            for key in ("objective",):
                text = str(task.get(key, "")).strip()
                if text:
                    return text
    return ""


def _has_v1_follow_up_tasks(plan: dict[str, Any]) -> bool:
    if not isinstance(plan, dict) or plan.get("plan_version") != 1:
        return False
    repaired = build_repaired_next_round_plan(plan)
    tasks = repaired.get("controller_tasks", [])
    if not isinstance(tasks, list):
        return False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        input_refs = task.get("input_refs", {})
        if not isinstance(input_refs, dict):
            continue
        if _string_list(input_refs.get("worker_report_ids", [])):
            return True
    return False


def _audit_repair_planned_tasks(
    *,
    trigger_audit_id: str,
    repair_queries: list[str],
) -> list[dict[str, Any]]:
    queries = [
        {"language": "auto", "query": query}
        for query in _dedupe_nonempty(repair_queries, limit=6)
    ]
    query_text = "；".join(item["query"] for item in queries)
    return [
        {
            "task_id": f"audit-repair-{trigger_audit_id}",
            "objective": "按 audit needs_revision 要求补充独立公开正文证据",
            "gap_type": "missing_direct_evidence",
            "routing_hint": "open_search_candidate",
            "source_scope": "open_web_after_whitelist_exhausted",
            "input_refs": {
                "worker_report_ids": [],
                "evidence_ids": [],
                "lead_ids": [],
            },
            "query_revisions": queries,
            "completion_check": "新增可审计 EvidenceCard，或说明只能得到 partial/adjacent evidence",
            "worker_brief": (
                "本轮是 audit needs_revision 后的开放补证。"
                f"优先使用这些 query：{query_text}。"
                "读取正文、评估开放来源质量，再创建 EvidenceCard。"
            ),
        }
    ]


def _network_consensus_text(
    topic: str,
    store: DomainStore,
    evidence_ids: list[str],
) -> str:
    for evidence_id in evidence_ids:
        evidence = store.evidence.get(evidence_id)
        if evidence is not None and evidence.claim.strip():
            return evidence.claim.strip()
    return f"围绕“{topic}”需要继续验证探测、预警与防护能力缺口"
