from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from equipment_deep_research.agents.provider import (
    AgentProvider,
    FakeAgentProvider,
    RealAgentProvider,
)
from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.domain.messages import RunCheckpoint
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
        if mode not in {"fake", "real"}:
            raise ValueError("mode must be fake or real")
        problem = ResearchProblem(
            topic=topic,
            research_route=research_route,
            selected_agent_ids=agent_ids or [],
        )
        route = problem.resolved_route()
        registry = AgentRegistry.load(self.agent_config_path)
        policy = load_preset_policy(self.preset_config_path)
        gate_policy = dict(policy.gate_policy)
        resolved_max_rounds = max_rounds or int(gate_policy.get("max_rounds", 5))
        selected_agents = registry.select_agents(agent_ids)
        selected_agent_ids = [agent.agent_id for agent in selected_agents]
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
            store = recovered.domain_store
            trace = recovered.trace_store
            checkpoint = recovered.checkpoint
            worker_reports = list(recovered.worker_reports)
            source_materials = list(recovered.source_materials)
            if checkpoint.status == "completed":
                if not self._outputs_complete(workspace.run_dir):
                    self._write_checkpoint_file(
                        workspace,
                        checkpoint,
                        recovered.last_savepoint_id,
                    )
                    self._write_recovered_outputs(
                        run_dir=workspace.run_dir,
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
                return self._result(
                    run_id=run_id,
                    run_dir=workspace.run_dir,
                    route=route,
                    store=store,
                )
            checkpoint = replace(checkpoint, resume_count=checkpoint.resume_count + 1)
            resumed_event = TraceEvent(
                event_id=f"trace-run-resumed-{checkpoint.resume_count}",
                event_type="run_resumed",
                actor="orchestrator",
                summary=f"run resumed for {topic}",
                payload={
                    "resume_count": checkpoint.resume_count,
                    "completed_task_ids": checkpoint.completed_task_ids,
                    "pending_task_ids": checkpoint.pending_task_ids,
                },
            )
            trace.append(resumed_event)
            savepoint_id = sqlite_store.commit(
                (self._checkpoint_proposal(checkpoint, f"resume-{checkpoint.resume_count}"),),
                (self._trace_proposal(resumed_event),),
            )
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)
        else:
            workspace = RunWorkspace.create(self.output_root, run_id)
            sqlite_store = SqliteRunStore(workspace.database_path, run_id=run_id)
            store = DomainStore()
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
                (self._checkpoint_proposal(checkpoint, "initial"),),
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
        )
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
                source_materials=[dict(item) for item in scheduler.source_materials],
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
            savepoint_id = sqlite_store.commit(domain_proposals, trace_proposals)
            scheduler.append_savepoint(report, savepoint_id)
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
        checkpoint = replace(
            checkpoint,
            completed_task_ids=[_task_id(agent_id) for agent_id in selected_agent_ids],
            pending_task_ids=[],
            task_statuses={
                _task_id(agent_id): "completed" for agent_id in selected_agent_ids
            },
            budget_remaining={
                **checkpoint.budget_remaining,
                "baseline_tasks": 0,
                "rounds": max(resolved_max_rounds - 1, 0),
            },
            status="completed",
            source_materials=[dict(item) for item in scheduler.source_materials],
            worker_reports=[to_plain(item) for item in worker_reports],
        )
        checkpoint.validate()
        final_domain_proposals = [
            *(self._domain_proposal("WinningMechanismStageOutput", item) for item in stage_outputs),
            *(self._domain_proposal("CapabilityImageItem", item) for item in images),
            *(self._domain_proposal("AgentRecommendation", item) for item in recommendations),
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
        self._write_checkpoint_file(workspace, checkpoint, savepoint_id)
        self._write_outputs(
            run_dir=workspace.run_dir,
            mode=mode,
            problem=problem,
            route=route,
            selected_agent_ids=selected_agent_ids,
            coverage=coverage,
            worker_reports=worker_reports,
            recommendations=recommendations,
            source_materials=scheduler.source_materials,
            store=store,
            trace=trace,
            report_body=report.body,
            analyst_confirmed=analyst_confirmed,
        )
        return self._result(
            run_id=run_id,
            run_dir=workspace.run_dir,
            route=route,
            store=store,
        )

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
        task_ids = [_task_id(agent_id) for agent_id in selected_agent_ids]
        checkpoint = RunCheckpoint(
            run_id=run_id,
            checkpoint_id=f"run-checkpoint-{run_id}",
            completed_task_ids=[],
            pending_task_ids=task_ids,
            round_index=1,
            budget_remaining={
                "rounds": max_rounds,
                "baseline_tasks": len(task_ids),
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
        ordered_tasks = [_task_id(agent_id) for agent_id in checkpoint.selected_agent_ids]
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
                    1 for item in ordered_tasks if statuses[item] != "completed"
                ),
            },
        )
        updated.validate()
        return updated

    @staticmethod
    def _domain_proposal(object_type: str, value: Any) -> DomainWriteProposal:
        payload = to_plain(value)
        id_fields = {
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
        payload = {
            "savepoint_id": savepoint_id,
            "checkpoint": to_plain(checkpoint),
        }
        history_path = workspace.checkpoints_dir / f"{savepoint_id}.json"
        if not history_path.exists():
            _atomic_write_json(history_path, payload)
        _atomic_write_json(workspace.checkpoints_dir / "latest.json", payload)

    @staticmethod
    def _outputs_complete(run_dir: Path) -> bool:
        return all(
            (run_dir / name).is_file()
            for name in (
                "report.md",
                "capability_images.json",
                "round_summary.json",
                "domain.jsonl",
                "trace.jsonl",
            )
        )

    def _write_recovered_outputs(
        self,
        *,
        run_dir: Path,
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
            run_dir=run_dir,
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
        run_dir: Path,
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
        (run_dir / "report.md").write_text(report_body, encoding="utf-8")
        (run_dir / "capability_images.json").write_text(
            json.dumps(
                [to_plain(item) for item in store.capability_images.values()],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
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
        (run_dir / "round_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        store.export_jsonl(run_dir / "domain.jsonl")
        trace.export_jsonl(run_dir / "trace.jsonl")

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


def _task_id(agent_id: str) -> str:
    return f"baseline:{agent_id}"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.is_symlink():
        raise ValueError(f"checkpoint path must not be a symlink: {path}")
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.is_symlink():
        raise ValueError(f"checkpoint temporary path must not be a symlink: {temporary}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
