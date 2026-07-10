from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from equipment_deep_research.agents.provider import AgentProvider, AgentRunRequest
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.models import TraceEvent
from equipment_deep_research.domain.store import DomainStore, TraceStore
from equipment_deep_research.harness.context import ContextPackBuilder
from equipment_deep_research.tools.materialization import EvidenceMaterializer


@dataclass(frozen=True)
class WorkerReport:
    agent_id: str
    status: str
    new_evidence_ids: list[str]
    packet_id: str
    handoff_summary: str
    session_path: str
    error: str = ""


class DiscoveryScheduler:
    def __init__(
        self,
        *,
        run_id: str,
        run_dir: Path,
        provider: AgentProvider,
        store: DomainStore,
        trace: TraceStore,
        mode: str = "fake",
        context_builder: ContextPackBuilder | None = None,
    ) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.provider = provider
        self.store = store
        self.trace = trace
        self.mode = mode
        self.context_builder = context_builder or ContextPackBuilder()
        self.sessions_dir = run_dir / "agent_sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.materializer = EvidenceMaterializer(run_dir / "artifacts")
        self.source_materials: list[dict] = []

    def run_baseline_agents(
        self,
        *,
        agents: list[AgentDef],
        topic: str,
        research_route: str,
    ) -> list[WorkerReport]:
        reports: list[WorkerReport] = []
        for agent in agents:
            reports.append(
                self._run_one(agent=agent, topic=topic, research_route=research_route)
            )
        return reports

    def _run_one(self, *, agent: AgentDef, topic: str, research_route: str) -> WorkerReport:
        session_path = self.sessions_dir / f"{agent.agent_id}.jsonl"
        before_evidence = set(self.store.evidence)
        try:
            context = self.context_builder.build_for_baseline_agent(
                agent=agent,
                topic=topic,
                research_route=research_route,
                store=self.store,
            )
            result = self.provider.run_baseline_agent(
                AgentRunRequest(
                    run_id=self.run_id,
                    agent=agent,
                    topic=topic,
                    research_route=research_route,
                    context=context.sections,
                )
            )
            materialized_refs: list[str] = []
            accepted_evidence_ids: list[str] = []
            for evidence in result.evidence:
                materialized = self.materializer.materialize(evidence, mode=self.mode)
                self.source_materials.append(materialized.material)
                materialized_refs.extend(materialized.material.get("artifact_refs", []))
                if materialized.material.get("formal_evidence_allowed", True):
                    self.store.add_evidence(materialized.evidence)
                    accepted_evidence_ids.append(materialized.evidence.evidence_id)
            packet = result.packet
            if packet.evidence_ids != accepted_evidence_ids:
                packet = type(packet)(
                    **{
                        **packet.__dict__,
                        "evidence_ids": accepted_evidence_ids,
                        "coverage_notes": [
                            *packet.coverage_notes,
                            "部分来源未通过网络安全或材料化校验，已从正式证据集中剔除。",
                        ],
                    }
                )
            self.store.add_baseline_packet(packet)
            self._append_session(
                session_path,
                {
                    "agent_id": agent.agent_id,
                    "context_sections": sorted(context.sections),
                    "raw_message": result.raw_message,
                    "packet_id": packet.packet_id,
                    "evidence_ids": packet.evidence_ids,
                    "materialized_artifact_refs": materialized_refs,
                },
            )
            new_evidence = sorted(set(self.store.evidence) - before_evidence)
            self.trace.append(
                TraceEvent(
                    event_id=f"trace-{agent.agent_id}-baseline",
                    event_type="baseline_agent_completed",
                    actor=agent.agent_id,
                    summary=packet.handoff_summary,
                    output_refs=[packet.packet_id, *new_evidence],
                    payload={"capability_tags": agent.capability_tags, "artifact_refs": materialized_refs},
                )
            )
            return WorkerReport(
                agent_id=agent.agent_id,
                status="completed",
                new_evidence_ids=new_evidence,
                packet_id=packet.packet_id,
                handoff_summary=packet.handoff_summary,
                session_path=str(session_path),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            self.trace.append(
                TraceEvent(
                    event_id=f"trace-{agent.agent_id}-failed",
                    event_type="baseline_agent_failed",
                    actor=agent.agent_id,
                    summary=str(exc),
                )
            )
            return WorkerReport(
                agent_id=agent.agent_id,
                status="failed",
                new_evidence_ids=[],
                packet_id="",
                handoff_summary="",
                session_path=str(session_path),
                error=str(exc),
            )

    @staticmethod
    def _append_session(path: Path, row: dict) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
