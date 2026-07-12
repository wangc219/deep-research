from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Callable

from equipment_deep_research.agents.provider import AgentProvider, AgentRunRequest
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.identifiers import (
    safe_identifier_path,
    validate_internal_identifier,
)
from equipment_deep_research.domain.models import TraceEvent, new_stable_id, now_iso
from equipment_deep_research.domain.store import DomainStore, TraceStore
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.harness.context import ContextPackBuilder
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.tools.artifacts import SecureArtifactStore
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
    worker_report_id: str = field(default_factory=lambda: new_stable_id("worker-report"))
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


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
        source_materials: list[dict[str, Any]] | None = None,
        session_store_factory: Callable[[str, Path], Any] | None = None,
        workspace: RunWorkspace | None = None,
    ) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.provider = provider
        self.store = store
        self.trace = trace
        self.mode = mode
        self.context_builder = context_builder or ContextPackBuilder()
        self.session_store_factory = session_store_factory
        self.workspace = workspace
        self.sessions_dir = run_dir / "agent_sessions"
        if workspace is None:
            if self.run_dir.is_symlink():
                raise ValueError("run_dir must not be a symlink")
            if self.sessions_dir.is_symlink():
                raise ValueError("agent_sessions must not be a symlink")
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            if self.sessions_dir.is_symlink():
                raise ValueError("agent_sessions must not be a symlink")
            if self.sessions_dir.resolve(strict=True).parent != self.run_dir.resolve(
                strict=True
            ):
                raise ValueError("agent_sessions must stay within run_dir")
        self.materializer = EvidenceMaterializer(
            artifact_store=(
                SecureArtifactStore.for_workspace(workspace)
                if workspace is not None
                else SecureArtifactStore(run_dir / "artifacts")
            )
        )
        self.source_materials = source_materials if source_materials is not None else []

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
                self.run_agent(
                    agent=agent,
                    topic=topic,
                    research_route=research_route,
                )
            )
        return reports

    def run_agent(
        self,
        *,
        agent: AgentDef,
        topic: str,
        research_route: str,
        raise_on_error: bool = False,
    ) -> WorkerReport:
        if self.workspace is not None:
            validated_agent_id = validate_internal_identifier(
                agent.agent_id,
                field_name="agent_id",
            )
            session_path = self.sessions_dir.joinpath(f"{validated_agent_id}.jsonl")
        else:
            session_path = safe_identifier_path(
                self.sessions_dir,
                agent.agent_id,
                suffix=".jsonl",
                field_name="agent_id",
            )
        session = self._open_session_store(session_path.name)
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
            session.append(
                {
                    "event_type": "baseline_result",
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
        except Exception as exc:
            if raise_on_error:
                raise
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
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def append_savepoint(
        self,
        report: WorkerReport,
        checkpoint_id: str,
        *,
        task_id: str,
        batch_hash: str,
    ) -> None:
        session_ref = Path(report.session_path).name
        session = self._open_session_store(session_ref)
        try:
            session.append(
                {
                    "event_type": "savepoint",
                    "agent_id": report.agent_id,
                    "task_id": task_id,
                    "checkpoint_id": checkpoint_id,
                    "batch_hash": batch_hash,
                    "worker_report_id": report.worker_report_id,
                    "packet_id": report.packet_id,
                    "evidence_ids": report.new_evidence_ids,
                    "created_at": now_iso(),
                    "schema_version": "1.0",
                },
            )
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def _open_session_store(self, session_ref: str) -> Any:
        if self.session_store_factory is not None:
            return self.session_store_factory(session_ref, self.sessions_dir)
        if self.workspace is not None:
            root_fd = self.workspace.dup_sessions_fd()
            try:
                return JsonlSessionStore(
                    session_ref,
                    root_fd=root_fd,
                    root_label=self.sessions_dir,
                )
            finally:
                os.close(root_fd)
        return JsonlSessionStore(session_ref, root_dir=self.sessions_dir)
