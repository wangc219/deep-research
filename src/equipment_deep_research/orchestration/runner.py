from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from equipment_deep_research.agents.provider import (
    AgentProvider,
    FakeAgentProvider,
    RealAgentProvider,
)
from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.domain.messages import FINALIZE_TASK_ID, RunCheckpoint
from equipment_deep_research.domain.models import ResearchProblem, TraceEvent, to_plain
from equipment_deep_research.domain.proposals import DomainWriteProposal, TraceProposal
from equipment_deep_research.domain.store import DomainStore, SqliteRunStore, TraceStore
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.harness.recovery import RecoveryManager
from equipment_deep_research.harness.scheduler import DiscoveryScheduler, WorkerReport
from equipment_deep_research.orchestration.coverage import (
    coverage_for_route,
    load_preset_policy,
)
from equipment_deep_research.orchestration.reporting import audit_run, render_report
from equipment_deep_research.orchestration.winning import WinningMechanismEngine
from equipment_deep_research.tools.permissions import ToolPermissionRegistry


class DeepResearchRunner:
    def __init__(
        self,
        *,
        project_root: Path,
        output_root: Path,
        agent_config_path: Path,
        preset_config_path: Path,
        provider_config_path: Path | None = None,
        evidence_config_path: Path | None = None,
        provider: AgentProvider | None = None,
        run_hook: Callable[[str, RunWorkspace], None] | None = None,
        session_store_factory: Callable[[str, Path], Any] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.output_root = Path(output_root)
        self.agent_config_path = Path(agent_config_path)
        self.preset_config_path = Path(preset_config_path)
        self.provider_config_path = (
            Path(provider_config_path)
            if provider_config_path is not None
            else self.project_root
            / "configs"
            / "equipment_deep_research"
            / "providers.yaml"
        )
        self.evidence_config_path = (
            Path(evidence_config_path)
            if evidence_config_path is not None
            else self.project_root
            / "configs"
            / "equipment_deep_research"
            / "evidence.yaml"
        )
        self.provider = provider
        self.run_hook = run_hook
        self.session_store_factory = session_store_factory
        if provider_config_path is not None and not self.provider_config_path.is_file():
            raise FileNotFoundError(
                f"configuration file does not exist: {self.provider_config_path}"
            )
        if evidence_config_path is not None and not self.evidence_config_path.is_file():
            raise FileNotFoundError(
                f"configuration file does not exist: {self.evidence_config_path}"
            )

    def run(
        self,
        *,
        mode: str,
        topic: str,
        research_route: str,
        run_id: str,
        agent_ids: list[str] | None = None,
        max_rounds: int | None = None,
        resume: bool = False,
        analyst_confirmed: bool = False,
    ) -> dict[str, Any]:
        resources = _RunResourceScope()
        try:
            return self._run_impl(
                mode=mode,
                topic=topic,
                research_route=research_route,
                run_id=run_id,
                agent_ids=agent_ids,
                max_rounds=max_rounds,
                resume=resume,
                analyst_confirmed=analyst_confirmed,
                resources=resources,
            )
        finally:
            resources.close()

    def _run_impl(
        self,
        *,
        mode: str,
        topic: str,
        research_route: str,
        run_id: str,
        agent_ids: list[str] | None,
        max_rounds: int | None,
        resume: bool,
        analyst_confirmed: bool,
        resources: "_RunResourceScope",
    ) -> dict[str, Any]:
        if mode not in {"fake", "real"}:
            raise ValueError("mode must be fake or real")
        requested_problem = ResearchProblem(
            topic=topic,
            research_route=research_route,
            selected_agent_ids=[],
        )
        route = requested_problem.resolved_route()
        registry = AgentRegistry.load(self.agent_config_path)
        policy = load_preset_policy(self.preset_config_path)
        gate_policy = dict(policy.gate_policy)
        resolved_max_rounds = max_rounds or int(gate_policy.get("max_rounds", 5))
        selected_agents = registry.select_agents(agent_ids)
        selected_agent_ids = [agent.agent_id for agent in selected_agents]
        problem = replace(requested_problem, selected_agent_ids=selected_agent_ids)
        permissions = ToolPermissionRegistry.default()
        for agent in selected_agents:
            permissions.validate_agent_tools(agent)
        coverage = coverage_for_route(
            route=route,
            selected_agents=selected_agents,
            policy=policy,
        )
        config_fingerprint = self._config_fingerprint(
            mode=mode,
            max_rounds=resolved_max_rounds,
            analyst_confirmed=analyst_confirmed,
        )

        if resume:
            recovered = RecoveryManager(self.output_root).load(
                run_id,
                topic=topic,
                research_route=research_route,
                resolved_route=route,
                selected_agent_ids=selected_agent_ids,
                config_fingerprint=config_fingerprint,
            )
            workspace = recovered.workspace
            sqlite_store = recovered.sqlite_store
            resources.bind(workspace, sqlite_store)
            store = recovered.domain_store
            trace = recovered.trace_store
            checkpoint = replace(
                recovered.checkpoint,
                resume_count=recovered.checkpoint.resume_count + 1,
            )
            problem = recovered.problem
            worker_reports = list(recovered.worker_reports)
            source_materials = _dedupe_plain_rows(recovered.source_materials)
            resumed_event = TraceEvent(
                event_id=f"trace-run-resumed-{checkpoint.resume_count}",
                event_type="run_resumed",
                actor="orchestrator",
                summary=f"run resumed for {topic}",
                payload={
                    "resume_count": checkpoint.resume_count,
                    "completed_task_ids": checkpoint.completed_task_ids,
                    "pending_task_ids": checkpoint.pending_task_ids,
                    "status": checkpoint.status,
                },
            )
            trace.append(resumed_event)
            savepoint_id = sqlite_store.commit(
                (self._checkpoint_proposal(checkpoint, f"resume-{checkpoint.resume_count}"),),
                (self._trace_proposal(resumed_event),),
            )
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)
            if checkpoint.status == "completed":
                self._write_recovered_outputs(
                    workspace=workspace,
                    mode=mode,
                    problem=problem,
                    route=route,
                    selected_agent_ids=selected_agent_ids,
                    coverage=coverage,
                    worker_reports=worker_reports,
                    source_materials=source_materials,
                    store=store,
                    trace=trace,
                    analyst_confirmed=analyst_confirmed,
                )
                result = self._result(
                    run_id=run_id,
                    run_dir=workspace.run_dir,
                    route=route,
                    store=store,
                )
                return result
        else:
            workspace = RunWorkspace.create(self.output_root, run_id)
            resources.bind_workspace(workspace)
            database_fd = workspace.dup_database_fd()
            database_dir_fd = workspace.dup_run_fd()
            try:
                sqlite_store = SqliteRunStore(
                    workspace.database_path,
                    run_id=run_id,
                    database_fd=database_fd,
                    database_dir_fd=database_dir_fd,
                )
            finally:
                os.close(database_fd)
                os.close(database_dir_fd)
            resources.bind_store(sqlite_store)
            self._emit_hook("after_workspace_created", workspace)
            store = DomainStore()
            store.add_problem(problem)
            trace = TraceStore()
            worker_reports: list[WorkerReport] = []
            source_materials: list[dict[str, Any]] = []
            checkpoint = self._initial_checkpoint(
                run_id=run_id,
                topic=topic,
                research_route=research_route,
                route=route,
                selected_agent_ids=selected_agent_ids,
                max_rounds=resolved_max_rounds,
                mode=mode,
                config_fingerprint=config_fingerprint,
            )
            started_event = TraceEvent(
                event_id="trace-run-started",
                event_type="run_started",
                actor="orchestrator",
                summary=f"run started for {topic}",
                payload={
                    "mode": mode,
                    "route": route,
                    "agent_ids": selected_agent_ids,
                    "analyst_confirmed": analyst_confirmed,
                },
            )
            trace.append(started_event)
            savepoint_id = sqlite_store.commit(
                (
                    self._domain_proposal("ResearchProblem", problem),
                    self._checkpoint_proposal(checkpoint, "initial"),
                ),
                (self._trace_proposal(started_event),),
            )
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)

        provider = self.provider or (
            FakeAgentProvider() if mode == "fake" else RealAgentProvider()
        )
        scheduler = DiscoveryScheduler(
            run_id=run_id,
            run_dir=workspace.run_dir,
            provider=provider,
            store=store,
            trace=trace,
            mode=mode,
            source_materials=source_materials,
            session_store_factory=self.session_store_factory,
            workspace=workspace,
        )
        resources.bind_scheduler(scheduler)
        reports_by_agent = {report.agent_id: report for report in worker_reports}
        agents_by_id = {agent.agent_id: agent for agent in selected_agents}
        for agent_id in selected_agent_ids:
            task_id = _task_id(agent_id)
            if checkpoint.task_statuses.get(task_id) == "completed":
                continue
            checkpoint = self._set_task_status(checkpoint, task_id, "running")
            savepoint_id = sqlite_store.commit(
                (
                    self._checkpoint_proposal(
                        checkpoint,
                        f"{task_id}-running-r{checkpoint.resume_count}",
                    ),
                ),
                (),
            )
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)

            evidence_before = set(store.evidence)
            packets_before = set(store.baseline_packets)
            trace_start = len(trace.events)
            report = scheduler.run_agent(
                agent=agents_by_id[agent_id],
                topic=topic,
                research_route=route,
                raise_on_error=True,
            )
            reports_by_agent[agent_id] = report
            worker_reports = [
                reports_by_agent[item]
                for item in selected_agent_ids
                if item in reports_by_agent
            ]
            checkpoint = self._set_task_status(checkpoint, task_id, "completed")
            checkpoint = replace(
                checkpoint,
                source_materials=_dedupe_plain_rows(scheduler.source_materials),
                worker_reports=[to_plain(item) for item in worker_reports],
            )
            domain_proposals = [
                *(
                    self._domain_proposal("EvidenceCard", store.evidence[item])
                    for item in sorted(set(store.evidence) - evidence_before)
                ),
                *(
                    self._domain_proposal(
                        "BaselineFindingPacket",
                        store.baseline_packets[item],
                    )
                    for item in sorted(set(store.baseline_packets) - packets_before)
                ),
                self._checkpoint_proposal(
                    checkpoint,
                    f"{task_id}-completed-r{checkpoint.resume_count}",
                ),
            ]
            trace_proposals = [
                self._trace_proposal(event) for event in trace.events[trace_start:]
            ]
            batch_hash = _proposal_batch_hash(domain_proposals, trace_proposals)
            savepoint_id = sqlite_store.commit(domain_proposals, trace_proposals)
            try:
                scheduler.append_savepoint(
                    report,
                    savepoint_id,
                    task_id=task_id,
                    batch_hash=batch_hash,
                )
            except Exception:
                self._record_session_write_failure(
                    sqlite_store=sqlite_store,
                    run_id=run_id,
                    report=report,
                    task_id=task_id,
                    checkpoint_id=savepoint_id,
                    batch_hash=batch_hash,
                )
                raise
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)

        self._emit_hook("after_baseline_agents", workspace)
        if checkpoint.task_statuses.get(FINALIZE_TASK_ID) != "completed":
            checkpoint = self._set_task_status(
                checkpoint,
                FINALIZE_TASK_ID,
                "running",
            )
            savepoint_id = sqlite_store.commit(
                (
                    self._checkpoint_proposal(
                        checkpoint,
                        f"{FINALIZE_TASK_ID}-running-r{checkpoint.resume_count}",
                    ),
                ),
                (),
            )
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)

            final_trace_start = len(trace.events)
            trace.append(
                TraceEvent(
                    event_id="trace-baseline-summary",
                    event_type="baseline_agents_summarized",
                    actor="orchestrator",
                    summary=f"{len(worker_reports)} baseline agents completed",
                    output_refs=[
                        report.packet_id for report in worker_reports if report.packet_id
                    ],
                )
            )
            engine = WinningMechanismEngine(
                min_confidence=float(gate_policy.get("min_stage_confidence", 0.7)),
                min_l2_feasibility=int(gate_policy.get("min_l2_feasibility", 3)),
            )
            stage_outputs, images, recommendations = engine.run(
                topic=topic,
                route=route,
                store=store,
                trace=trace,
                coverage=coverage,
            )
            for recommendation in recommendations:
                store.add_recommendation(recommendation)
            audit = audit_run(
                store=store,
                coverage=coverage,
                max_rounds=resolved_max_rounds,
                source_materials=scheduler.source_materials,
            )
            store.add_audit(audit)
            report = render_report(
                topic=topic,
                route=route,
                store=store,
                coverage=coverage,
                audit=audit,
            )
            store.add_report(report)
            self._emit_hook("after_finalize_engine", workspace)
            checkpoint = self._set_task_status(
                checkpoint,
                FINALIZE_TASK_ID,
                "completed",
            )
            checkpoint = replace(
                checkpoint,
                budget_remaining={
                    **checkpoint.budget_remaining,
                    "baseline_tasks": 0,
                    "finalize_tasks": 0,
                    "rounds": max(resolved_max_rounds - 1, 0),
                },
                status="completed",
                source_materials=_dedupe_plain_rows(scheduler.source_materials),
                worker_reports=[to_plain(item) for item in worker_reports],
            )
            checkpoint.validate()
            final_domain_proposals = [
                *(
                    self._domain_proposal("WinningMechanismStageOutput", item)
                    for item in stage_outputs
                ),
                *(
                    self._domain_proposal("CapabilityImageItem", item)
                    for item in images
                ),
                *(
                    self._domain_proposal("AgentRecommendation", item)
                    for item in recommendations
                ),
                self._domain_proposal("AuditResult", audit),
                self._domain_proposal("ResearchReport", report),
                self._checkpoint_proposal(
                    checkpoint,
                    f"completed-r{checkpoint.resume_count}",
                ),
            ]
            final_trace_proposals = [
                self._trace_proposal(event) for event in trace.events[final_trace_start:]
            ]
            savepoint_id = sqlite_store.commit(
                final_domain_proposals,
                final_trace_proposals,
            )
            self._emit_hook("after_final_commit", workspace)
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)
        else:  # pragma: no cover - normalized completed checkpoints return above
            recommendations = list(store.recommendations.values())
            report = next(iter(store.reports.values()))

        self._emit_hook("before_outputs", workspace)
        self._write_outputs(
            workspace=workspace,
            mode=mode,
            problem=problem,
            route=route,
            selected_agent_ids=selected_agent_ids,
            coverage=coverage,
            worker_reports=worker_reports,
            recommendations=recommendations,
            source_materials=_dedupe_plain_rows(scheduler.source_materials),
            store=store,
            trace=trace,
            report_body=report.body,
            analyst_confirmed=analyst_confirmed,
        )
        result = self._result(
            run_id=run_id,
            run_dir=workspace.run_dir,
            route=route,
            store=store,
        )
        return result

    def _initial_checkpoint(
        self,
        *,
        run_id: str,
        topic: str,
        research_route: str,
        route: str,
        selected_agent_ids: list[str],
        max_rounds: int,
        mode: str,
        config_fingerprint: str,
    ) -> RunCheckpoint:
        task_ids = [
            *[_task_id(agent_id) for agent_id in selected_agent_ids],
            FINALIZE_TASK_ID,
        ]
        checkpoint = RunCheckpoint(
            run_id=run_id,
            checkpoint_id=f"run-checkpoint-{run_id}",
            completed_task_ids=[],
            pending_task_ids=task_ids,
            round_index=1,
            budget_remaining={
                "rounds": max_rounds,
                "baseline_tasks": len(selected_agent_ids),
                "finalize_tasks": 1,
            },
            status="running",
            task_statuses={task_id: "pending" for task_id in task_ids},
            topic=topic,
            research_route=research_route,
            resolved_route=route,
            selected_agent_ids=selected_agent_ids,
            source_materials=[],
            worker_reports=[],
            mode=mode,
            config_fingerprint=config_fingerprint,
        )
        checkpoint.validate()
        return checkpoint

    @staticmethod
    def _set_task_status(
        checkpoint: RunCheckpoint,
        task_id: str,
        status: str,
    ) -> RunCheckpoint:
        statuses = dict(checkpoint.task_statuses)
        statuses[task_id] = status
        ordered_tasks = [
            *[_task_id(agent_id) for agent_id in checkpoint.selected_agent_ids],
            FINALIZE_TASK_ID,
        ]
        completed = [item for item in ordered_tasks if statuses[item] == "completed"]
        pending = [item for item in ordered_tasks if statuses[item] == "pending"]
        updated = replace(
            checkpoint,
            completed_task_ids=completed,
            pending_task_ids=pending,
            task_statuses=statuses,
            budget_remaining={
                **checkpoint.budget_remaining,
                "baseline_tasks": sum(
                    1
                    for item in ordered_tasks
                    if item != FINALIZE_TASK_ID and statuses[item] != "completed"
                ),
                "finalize_tasks": int(
                    statuses.get(FINALIZE_TASK_ID) != "completed"
                ),
            },
        )
        updated.validate()
        return updated

    @staticmethod
    def _domain_proposal(object_type: str, value: Any) -> DomainWriteProposal:
        payload = to_plain(value)
        id_fields = {
            "ResearchProblem": "problem_id",
            "EvidenceCard": "evidence_id",
            "BaselineFindingPacket": "packet_id",
            "AgentRecommendation": "recommendation_id",
            "WinningMechanismStageOutput": "stage_id",
            "CapabilityImageItem": "capability_id",
            "AuditResult": "audit_id",
            "ResearchReport": "report_id",
        }
        object_id = str(payload[id_fields[object_type]])
        key = f"{object_type}:{object_id}"
        return DomainWriteProposal(
            proposal_id=f"domain-{key}",
            object_type=object_type,
            operation="upsert",
            payload=payload,
            idempotency_key=f"domain:{key}",
        )

    @staticmethod
    def _checkpoint_proposal(
        checkpoint: RunCheckpoint,
        step: str,
    ) -> DomainWriteProposal:
        key = f"workflow:{checkpoint.run_id}:{step}"
        return DomainWriteProposal(
            proposal_id=key,
            object_type="RunCheckpoint",
            operation="upsert",
            payload=to_plain(checkpoint),
            idempotency_key=key,
        )

    @staticmethod
    def _trace_proposal(event: TraceEvent) -> TraceProposal:
        return TraceProposal(
            proposal_id=event.event_id,
            event_type=event.event_type,
            actor=event.actor,
            payload=to_plain(event),
        )

    @staticmethod
    def _record_session_write_failure(
        *,
        sqlite_store: SqliteRunStore,
        run_id: str,
        report: WorkerReport,
        task_id: str,
        checkpoint_id: str,
        batch_hash: str,
    ) -> None:
        session_ref = Path(report.session_path).name
        marker_seed = f"{run_id}:{task_id}:{checkpoint_id}:{batch_hash}:{session_ref}"
        marker_id = f"runner-session-{sha256(marker_seed.encode('utf-8')).hexdigest()[:24]}"
        marker_event = TraceEvent(
            event_id=marker_id,
            event_type="session_write_failed",
            actor=report.agent_id,
            summary=f"session savepoint write failed for {task_id}",
            payload={
                "marker_id": marker_id,
                "committed_checkpoint_id": checkpoint_id,
                "batch_hash": batch_hash,
                "turn_index": 1,
                "task_id": task_id,
                "agent_id": report.agent_id,
                "execution_id": report.worker_report_id,
                "session_ref": session_ref,
                "session_event": "savepoint",
                "recovery_status": "reconcile_required",
            },
        )
        sqlite_store.commit(
            (),
            (
                TraceProposal(
                    proposal_id=marker_id,
                    event_type=marker_event.event_type,
                    actor=report.agent_id,
                    payload=to_plain(marker_event),
                ),
            ),
        )

    def _config_fingerprint(
        self,
        *,
        mode: str,
        max_rounds: int,
        analyst_confirmed: bool,
    ) -> str:
        files = {
            "agents": self.agent_config_path,
            "presets": self.preset_config_path,
            "providers": self.provider_config_path,
            "evidence": self.evidence_config_path,
        }
        payload = {
            "files": {
                name: sha256(path.read_bytes()).hexdigest()
                for name, path in files.items()
            },
            "mode": mode,
            "max_rounds": max_rounds,
            "analyst_confirmed": analyst_confirmed,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{sha256(encoded).hexdigest()}"

    @staticmethod
    def _write_checkpoint_file(
        workspace: RunWorkspace,
        checkpoint: RunCheckpoint,
        savepoint_id: str,
    ) -> None:
        encoded = json.dumps(
            {
                "savepoint_id": savepoint_id,
                "checkpoint": to_plain(checkpoint),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        workspace.write_checkpoint_text(f"{savepoint_id}.json", encoded)
        workspace.write_checkpoint_text("latest.json", encoded)

    def _write_recovered_outputs(
        self,
        *,
        workspace: RunWorkspace,
        mode: str,
        problem: ResearchProblem,
        route: str,
        selected_agent_ids: list[str],
        coverage: dict[str, Any],
        worker_reports: list[WorkerReport],
        source_materials: list[dict[str, Any]],
        store: DomainStore,
        trace: TraceStore,
        analyst_confirmed: bool,
    ) -> None:
        if not store.reports:
            raise RuntimeError("completed checkpoint has no research report")
        report = next(iter(store.reports.values()))
        self._write_outputs(
            workspace=workspace,
            mode=mode,
            problem=problem,
            route=route,
            selected_agent_ids=selected_agent_ids,
            coverage=coverage,
            worker_reports=worker_reports,
            recommendations=list(store.recommendations.values()),
            source_materials=source_materials,
            store=store,
            trace=trace,
            report_body=report.body,
            analyst_confirmed=analyst_confirmed,
        )

    def _write_outputs(
        self,
        *,
        workspace: RunWorkspace,
        mode: str,
        problem: ResearchProblem,
        route: str,
        selected_agent_ids: list[str],
        coverage: dict[str, Any],
        worker_reports: list[Any],
        recommendations: list[Any],
        source_materials: list[dict[str, Any]],
        store: DomainStore,
        trace: TraceStore,
        report_body: str,
        analyst_confirmed: bool,
    ) -> None:
        workspace.write_run_text("report.md", report_body)
        workspace.write_run_text(
            "capability_images.json",
            json.dumps(
                [to_plain(item) for item in store.capability_images.values()],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
        )
        summary = {
            "mode": mode,
            "analyst_confirmed": analyst_confirmed,
            "problem": to_plain(problem),
            "resolved_route": route,
            "selected_agent_ids": selected_agent_ids,
            "coverage": coverage,
            "worker_reports": [to_plain(report) for report in worker_reports],
            "recall_requests": [
                to_plain(recall)
                for stage in store.stage_outputs.values()
                for recall in stage.recall_requests
            ],
            "agent_recommendations": [to_plain(item) for item in recommendations],
            "source_materials": source_materials,
            "store_summary": store.summary(),
            "trace_summary": trace.summary(),
        }
        workspace.write_run_text(
            "round_summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        )
        workspace.write_run_text("domain.jsonl", store.jsonl_text())
        workspace.write_run_text("trace.jsonl", trace.jsonl_text())

    @staticmethod
    def _result(
        *,
        run_id: str,
        run_dir: Path,
        route: str,
        store: DomainStore,
    ) -> dict[str, Any]:
        if not store.audits:
            raise RuntimeError("completed run has no audit result")
        audit = next(iter(store.audits.values()))
        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "route": route,
            "status": "completed",
            "report_path": str(run_dir / "report.md"),
            "capability_images_path": str(run_dir / "capability_images.json"),
            "summary_path": str(run_dir / "round_summary.json"),
            "audit_status": audit.status,
            "capability_count": len(store.capability_images),
            "stage_count": len(store.stage_outputs),
        }

    def _emit_hook(self, event: str, workspace: RunWorkspace) -> None:
        if self.run_hook is not None:
            self.run_hook(event, workspace)


def _task_id(agent_id: str) -> str:
    return f"baseline:{agent_id}"


def _proposal_batch_hash(
    domain_proposals: Sequence[DomainWriteProposal],
    trace_proposals: Sequence[TraceProposal],
) -> str:
    rows = [
        {"channel": "domain", **proposal.to_plain()}
        for proposal in domain_proposals
    ] + [
        {"channel": "trace", **proposal.to_plain()}
        for proposal in trace_proposals
    ]
    rows.sort(key=lambda row: (str(row["proposal_id"]), str(row["channel"])))
    encoded = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _dedupe_plain_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        encoded = json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        if encoded in seen:
            continue
        seen.add(encoded)
        unique.append(dict(row))
    return unique


class _RunResourceScope:
    def __init__(self) -> None:
        self.workspace: RunWorkspace | None = None
        self.sqlite_store: SqliteRunStore | None = None
        self.scheduler: DiscoveryScheduler | None = None

    def bind_workspace(self, workspace: RunWorkspace) -> None:
        self.workspace = workspace

    def bind_store(self, sqlite_store: SqliteRunStore) -> None:
        self.sqlite_store = sqlite_store

    def bind_scheduler(self, scheduler: DiscoveryScheduler) -> None:
        self.scheduler = scheduler

    def bind(
        self,
        workspace: RunWorkspace,
        sqlite_store: SqliteRunStore,
    ) -> None:
        self.bind_workspace(workspace)
        self.bind_store(sqlite_store)

    def close(self) -> None:
        scheduler, self.scheduler = self.scheduler, None
        sqlite_store, self.sqlite_store = self.sqlite_store, None
        workspace, self.workspace = self.workspace, None
        try:
            if scheduler is not None:
                scheduler.close()
        finally:
            try:
                if sqlite_store is not None:
                    sqlite_store.close()
            finally:
                if workspace is not None:
                    workspace.close()
