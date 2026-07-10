from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from equipment_deep_research.agents.provider import FakeAgentProvider, RealAgentProvider
from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.domain.models import ResearchProblem, TraceEvent, to_plain
from equipment_deep_research.domain.store import DomainStore, TraceStore
from equipment_deep_research.harness.scheduler import DiscoveryScheduler
from equipment_deep_research.orchestration.coverage import coverage_for_route, load_preset_policy
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
    ) -> None:
        self.project_root = project_root
        self.output_root = output_root
        self.agent_config_path = agent_config_path
        self.preset_config_path = preset_config_path

    def run(
        self,
        *,
        mode: str,
        topic: str,
        research_route: str,
        run_id: str,
        agent_ids: list[str] | None = None,
        max_rounds: int | None = None,
    ) -> dict[str, Any]:
        if mode not in {"fake", "real"}:
            raise ValueError("mode must be fake or real")
        problem = ResearchProblem(topic=topic, research_route=research_route, selected_agent_ids=agent_ids or [])
        route = problem.resolved_route()
        registry = AgentRegistry.load(self.agent_config_path)
        policy = load_preset_policy(self.preset_config_path)
        gate_policy = dict(policy.gate_policy)
        max_rounds = max_rounds or int(gate_policy.get("max_rounds", 5))
        selected_agents = registry.select_agents(agent_ids)
        permissions = ToolPermissionRegistry.default()
        for agent in selected_agents:
            permissions.validate_agent_tools(agent)
        coverage = coverage_for_route(route=route, selected_agents=selected_agents, policy=policy)
        run_dir = self.output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        store = DomainStore()
        trace = TraceStore()
        trace.append(
            TraceEvent(
                event_id="trace-run-started",
                event_type="run_started",
                actor="orchestrator",
                summary=f"run started for {topic}",
                payload={"mode": mode, "route": route, "agent_ids": [agent.agent_id for agent in selected_agents]},
            )
        )
        provider = FakeAgentProvider() if mode == "fake" else RealAgentProvider()
        scheduler = DiscoveryScheduler(
            run_id=run_id,
            run_dir=run_dir,
            provider=provider,
            store=store,
            trace=trace,
            mode=mode,
        )
        worker_reports = scheduler.run_baseline_agents(
            agents=selected_agents,
            topic=topic,
            research_route=route,
        )
        trace.append(
            TraceEvent(
                event_id="trace-baseline-summary",
                event_type="baseline_agents_summarized",
                actor="orchestrator",
                summary=f"{len(worker_reports)} baseline agents completed",
                output_refs=[report.packet_id for report in worker_reports if report.packet_id],
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
        audit = audit_run(
            store=store,
            coverage=coverage,
            max_rounds=max_rounds,
            source_materials=scheduler.source_materials,
        )
        store.add_audit(audit)
        report = render_report(topic=topic, route=route, store=store, coverage=coverage, audit=audit)
        store.add_report(report)
        self._write_outputs(
            run_dir=run_dir,
            mode=mode,
            problem=problem,
            route=route,
            selected_agent_ids=[agent.agent_id for agent in selected_agents],
            coverage=coverage,
            worker_reports=worker_reports,
            recommendations=recommendations,
            source_materials=scheduler.source_materials,
            store=store,
            trace=trace,
            report_body=report.body,
        )
        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "route": route,
            "report_path": str(run_dir / "report.md"),
            "capability_images_path": str(run_dir / "capability_images.json"),
            "summary_path": str(run_dir / "round_summary.json"),
            "audit_status": audit.status,
            "capability_count": len(images),
            "stage_count": len(stage_outputs),
        }

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
    ) -> None:
        (run_dir / "report.md").write_text(report_body, encoding="utf-8")
        (run_dir / "capability_images.json").write_text(
            json.dumps([to_plain(item) for item in store.capability_images.values()], ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        summary = {
            "mode": mode,
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
