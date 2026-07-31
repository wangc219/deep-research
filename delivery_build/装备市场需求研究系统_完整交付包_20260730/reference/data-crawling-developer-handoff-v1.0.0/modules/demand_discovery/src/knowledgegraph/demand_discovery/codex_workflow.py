"""Independent Codex-driven demand discovery workflow.

This module deliberately does not call the existing Phase 5 autonomous
research controller. It reuses durable domain objects and source validation,
but owns its workflow control so Codex can replace the role execution layer
without changing the current main chain.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Protocol
from uuid import uuid4

from knowledgegraph.demand_discovery.domain.judgement import (
    JudgementItem,
    JudgementReport,
)
from knowledgegraph.demand_discovery.domain.judgement_plan import (
    assess_next_round_plan,
    build_repaired_next_round_plan,
)
from knowledgegraph.demand_discovery.domain.models import (
    AuditReport,
    CandidateDemand,
    DemandReport,
    DomainTraceEvent,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.report import render_demand_report
from knowledgegraph.demand_discovery.domain.research_state import ResearchRound
from knowledgegraph.demand_discovery.domain.source_registry import (
    SourceRegistry,
    default_source_whitelist_path,
)
from knowledgegraph.demand_discovery.domain.source_strategy import (
    SourceStrategy,
    SourceStrategyPlanner,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.harness.judge_plan_routing import (
    worker_assignments_from_judgement,
)
from knowledgegraph.demand_discovery.harness.report_publisher import publish_report
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext
from knowledgegraph.demand_discovery.harness.types import ToolCall, ToolResult
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore
from knowledgegraph.demand_discovery.tools.discovery import (
    create_classify_source_page_tool,
    create_download_document_tool,
)
from knowledgegraph.demand_discovery.tools.documents import create_read_document_tool
from knowledgegraph.demand_discovery.tools.network import (
    HttpTransport,
    create_fetch_page_tool,
)


ROLE_ORDER = ("planner", "reader", "judge", "synthesizer", "auditor", "reporter")
AGENT_PROMPT_ROLES = {"reader", "judge", "auditor", "reporter"}
REPORT_SECTION_KEYWORDS = ("结论", "能力缺口", "证据", "限制", "后续")


@dataclass(frozen=True)
class CodexWorkflowConfig:
    topic: str
    output_root: Path
    run_id: str = "demand-discovery-codex"
    source_whitelist_path: str | Path | None = None
    seed_urls: list[str] | None = None
    allow_browser: bool = False
    max_rounds: int = 1
    project_root: Path | None = None
    codex_home: Path | None = None
    codex_model: str = "gpt-5.5"
    reasoning_effort: str = "high"
    timeout_seconds: int = 900
    enable_web_search: bool = True
    max_worker_tasks_per_round: int = 3
    max_report_rewrites: int = 1


@dataclass(frozen=True)
class CodexWorkflowResult:
    run_id: str
    run_dir: Path
    source_strategy_id: str
    round_summary_path: Path
    domain_path: Path
    trace_path: Path
    report_path: Path


class RoleRunner(Protocol):
    def run_role(
        self,
        role: str,
        payload: dict[str, object],
        *,
        run_dir: Path,
    ) -> dict[str, object]:
        ...


class SourceMaterializer(Protocol):
    def materialize_reader_output(
        self,
        *,
        store: DomainStore,
        registry: SourceRegistry,
        reader_output: dict[str, object],
        import_result: dict[str, list[str]],
        run_dir: Path,
        run_id: str,
        topic: str,
        round_id: str,
        assignment_index: int,
        assignment: dict[str, object],
        created_by: str,
    ) -> list[dict[str, object]]:
        ...


class CodexRoleRunner:
    """Run one workflow role through Codex CLI and parse a JSON object result."""

    def __init__(self, config: CodexWorkflowConfig) -> None:
        self.config = config

    def run_role(
        self,
        role: str,
        payload: dict[str, object],
        *,
        run_dir: Path,
    ) -> dict[str, object]:
        prompt = _role_prompt(role, payload)
        output_dir = run_dir / "codex_last_messages"
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="dd_codex_role_") as temp_dir:
            output_path = Path(temp_dir) / f"{role}_last_message.txt"
            completed = subprocess.run(
                _codex_command(self.config, output_path),
                input=prompt,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_codex_env(self.config),
                timeout=max(1, int(self.config.timeout_seconds)),
                check=False,
            )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(
                    f"Codex role {role} failed with exit {completed.returncode}: {message}"
                )
            if not output_path.exists():
                raise RuntimeError(f"Codex role {role} did not write final message")
            final_text = output_path.read_text(encoding="utf-8")
            (output_dir / f"{role}.txt").write_text(final_text, encoding="utf-8")
        result = _extract_json_object(final_text)
        if not isinstance(result, dict):
            raise RuntimeError(f"Codex role {role} did not return a JSON object")
        return result


class DefaultSourceMaterializer:
    """Fetch and read accepted reader evidence into local artifacts."""

    def __init__(
        self,
        *,
        http_transport: HttpTransport | None = None,
        fetch_timeout_ms: int = 30_000,
        read_paragraph_limit: int = 80,
    ) -> None:
        self.http_transport = http_transport
        self.fetch_timeout_ms = fetch_timeout_ms
        self.read_paragraph_limit = read_paragraph_limit

    def materialize_reader_output(
        self,
        *,
        store: DomainStore,
        registry: SourceRegistry,
        reader_output: dict[str, object],
        import_result: dict[str, list[str]],
        run_dir: Path,
        run_id: str,
        topic: str,
        round_id: str,
        assignment_index: int,
        assignment: dict[str, object],
        created_by: str,
    ) -> list[dict[str, object]]:
        del reader_output, assignment, created_by
        artifacts = ArtifactStore(run_dir / "artifacts")
        ctx = ToolExecutionContext(
            run_id=run_id,
            agent_run_id=f"codex-materializer-{round_id}-{assignment_index}",
            worker_id="codex-reader-materializer",
            permissions={"mode": "codex_source_materialization"},
        )
        fetch_page = create_fetch_page_tool(
            registry,
            artifacts,
            http_transport=self.http_transport,
            timeout_ms=self.fetch_timeout_ms,
        )
        download_document = create_download_document_tool(
            store,
            registry,
            artifacts,
            http_transport=self.http_transport,
            timeout_ms=self.fetch_timeout_ms,
        )
        classify_source_page = create_classify_source_page_tool(artifacts)
        read_document = create_read_document_tool(artifacts)

        rows: list[dict[str, object]] = []
        for evidence_id in import_result["accepted_evidence_ids"]:
            evidence = store.evidence.get(evidence_id)
            if evidence is None:
                continue
            source = store.sources.get(evidence.source_id)
            if source is None:
                rows.append(
                    _failed_source_material(
                        evidence_id=evidence.evidence_id,
                        source_id=evidence.source_id,
                        url="",
                        error="source record missing after reader import",
                    )
                )
                continue
            rows.append(
                self._materialize_one(
                    store=store,
                    artifacts=artifacts,
                    ctx=ctx,
                    fetch_page=fetch_page,
                    download_document=download_document,
                    classify_source_page=classify_source_page,
                    read_document=read_document,
                    topic=topic,
                    evidence=evidence,
                    source=source,
                )
            )
        return rows

    def _materialize_one(
        self,
        *,
        store: DomainStore,
        artifacts: ArtifactStore,
        ctx: ToolExecutionContext,
        fetch_page: Any,
        download_document: Any,
        classify_source_page: Any,
        read_document: Any,
        topic: str,
        evidence: EvidenceCard,
        source: SourceRecord,
    ) -> dict[str, object]:
        url = source.url_or_path
        if _looks_like_download_url(url):
            result = _run_tool_sync(
                download_document,
                ToolCall(
                    id=f"materialize-{evidence.evidence_id}-download",
                    name=download_document.name,
                    arguments={"url": url},
                ),
                ctx,
            )
            if result.is_error:
                return _failed_source_material(
                    evidence_id=evidence.evidence_id,
                    source_id=evidence.source_id,
                    url=url,
                    error=result.content,
                )
            artifact_ref = str(result.details.get("raw_artifact_ref", ""))
            text_ref = str(result.details.get("text_artifact_ref", ""))
            page_type = "download_document"
        else:
            result = _run_tool_sync(
                fetch_page,
                ToolCall(
                    id=f"materialize-{evidence.evidence_id}-fetch",
                    name=fetch_page.name,
                    arguments={"url": url},
                ),
                ctx,
            )
            if result.is_error:
                return _failed_source_material(
                    evidence_id=evidence.evidence_id,
                    source_id=evidence.source_id,
                    url=url,
                    error=result.content,
                )
            artifact_ref = str(result.details.get("artifact_ref", ""))
            text_ref = str(result.details.get("simplified_ref", ""))
            page_type = ""
            if artifact_ref:
                classified = _run_tool_sync(
                    classify_source_page,
                    ToolCall(
                        id=f"materialize-{evidence.evidence_id}-classify",
                        name=classify_source_page.name,
                        arguments={
                            "url": url,
                            "artifact_ref": artifact_ref,
                            "topic": topic,
                        },
                    ),
                    ctx,
                )
                if not classified.is_error:
                    page_type = str(classified.details.get("page_type", ""))

        if not text_ref:
            return {
                "material_id": _source_material_id(evidence.evidence_id, artifact_ref or url),
                "evidence_id": evidence.evidence_id,
                "source_id": evidence.source_id,
                "url": url,
                "artifact_ref": artifact_ref,
                "simplified_ref": "",
                "page_type": page_type,
                "matched_source_location": "",
                "read_excerpt": "",
                "status": "fetched",
                "reason": "artifact stored but no readable text artifact was available",
            }

        read_result = _run_tool_sync(
            read_document,
            ToolCall(
                id=f"materialize-{evidence.evidence_id}-read",
                name=read_document.name,
                arguments={
                    "artifact_ref": text_ref,
                    "offset": 0,
                    "limit": self.read_paragraph_limit,
                },
            ),
            ctx,
        )
        paragraphs = _artifact_paragraphs(artifacts, text_ref)
        match = _best_evidence_paragraph(evidence, paragraphs)
        matched_location = ""
        read_excerpt = ""
        status = "fetched"
        if match is not None:
            para_index, paragraph = match
            matched_location = f"{text_ref}#para:{para_index}"
            read_excerpt = _clip_text(paragraph, 700)
            status = "matched"
            store.upsert_evidence(
                replace(
                    evidence,
                    excerpt=read_excerpt,
                    source_location=matched_location,
                )
            )
        return {
            "material_id": _source_material_id(evidence.evidence_id, text_ref),
            "evidence_id": evidence.evidence_id,
            "source_id": evidence.source_id,
            "url": url,
            "artifact_ref": artifact_ref,
            "simplified_ref": text_ref,
            "page_type": page_type,
            "matched_source_location": matched_location,
            "read_excerpt": read_excerpt,
            "read_document": {
                "is_error": read_result.is_error,
                "returned_range": list(read_result.details.get("returned_range", [])),
                "total_paragraphs": read_result.details.get("total_paragraphs"),
                "truncated": bool(read_result.details.get("truncated", False)),
            },
            "status": status,
            "reason": (
                "matched reader evidence to stored body paragraph"
                if status == "matched"
                else "stored readable body artifact but did not find a confident paragraph match"
            ),
        }


class _NullSourceMaterializer:
    def materialize_reader_output(self, **_: object) -> list[dict[str, object]]:
        return []


def run_codex_workflow_sync(
    config: CodexWorkflowConfig,
    *,
    role_runner: RoleRunner | None = None,
    source_materializer: SourceMaterializer | None = None,
) -> CodexWorkflowResult:
    if not config.topic.strip():
        raise ValueError("topic is required")
    run_dir = config.output_root / config.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    role_outputs_dir = run_dir / "role_outputs"
    role_outputs_dir.mkdir(parents=True, exist_ok=True)

    registry = SourceRegistry.load(
        config.source_whitelist_path or default_source_whitelist_path()
    )
    strategy = SourceStrategyPlanner(registry).plan(
        topic=config.topic,
        seed_urls=list(config.seed_urls or []),
        allow_browser=config.allow_browser,
        min_sources=4,
    )
    store = DomainStore(tier_status_cap=registry.tier_status_cap)
    store.upsert_source_strategy(strategy)
    _append_trace(
        store,
        run_id=config.run_id,
        event_type="source_strategy_selected",
        actor="codex_workflow",
        target_type="SourceStrategy",
        target_id=strategy.strategy_id,
        output_refs=[strategy.strategy_id],
        summary=f"selected source strategy {strategy.strategy_id}",
        payload={"execution": "independent_codex_workflow"},
    )
    runner = role_runner or CodexRoleRunner(config)
    materializer = _source_materializer_for_run(
        role_runner=role_runner,
        source_materializer=source_materializer,
    )
    role_outputs: dict[str, dict[str, object]] = {}
    accepted_source_ids: list[str] = []
    rejected_source_ids: list[str] = []
    accepted_evidence_ids: list[str] = []
    rejected_evidence_ids: list[str] = []
    source_materials: list[dict[str, object]] = []

    base_payload: dict[str, object] = {
        "run_id": config.run_id,
        "topic": config.topic,
        "source_strategy": strategy.to_dict(),
        "whitelist_sources": _whitelist_payload(registry),
        "rules": _workflow_rules(),
    }

    planner_output = _run_role(
        runner,
        "planner",
        base_payload,
        run_dir=run_dir,
        role_outputs_dir=role_outputs_dir,
        store=store,
        run_id=config.run_id,
    )
    role_outputs["planner"] = planner_output
    assignments = _initial_worker_assignments(planner_output, topic=config.topic)
    rounds: list[dict[str, object]] = []
    all_worker_reports: list[dict[str, object]] = []
    previous_judgement: JudgementReport | None = None
    judgement: JudgementReport | None = None
    round_count = 0
    max_rounds = max(1, int(config.max_rounds or 1))
    max_worker_tasks = max(1, int(config.max_worker_tasks_per_round or 1))
    for round_index in range(1, max_rounds + 1):
        round_id = f"round-{round_index}"
        round_count = round_index
        research_round = ResearchRound(
            round_id=round_id,
            run_id=config.run_id,
            index=round_index,
            topic=config.topic,
            hypothesis=f"Codex workflow researches demand signals for: {config.topic}",
            source_strategy_id=strategy.strategy_id,
            worker_report_ids=[],
            judgement_id=None,
            next_round_plan={},
            stop_reason=None,
            status="planned",
            created_at=_now(),
            updated_at=_now(),
        )
        store.upsert_research_round(research_round)
        if not assignments:
            assignments = _initial_worker_assignments({}, topic=config.topic)
        round_worker_reports: list[dict[str, object]] = []
        round_reader_outputs: list[dict[str, object]] = []
        round_source_materials: list[dict[str, object]] = []
        for assignment_index, assignment in enumerate(
            assignments[:max_worker_tasks],
            start=1,
        ):
            if round_index > 1:
                _append_trace(
                    store,
                    run_id=config.run_id,
                    event_type="judge_worker_assignment_created",
                    actor="codex-judge",
                    target_type="CodexWorkerAssignment",
                    target_id=str(assignment.get("task_id", f"task-{assignment_index}")),
                    input_refs=_assignment_input_refs(assignment),
                    output_refs=[str(assignment.get("task_id", f"task-{assignment_index}"))],
                    summary="judge next-round plan routed to Codex reader",
                    payload={"assignment": dict(assignment), "round_id": round_id},
                )
            reader_output_name = f"{round_id}_reader_{assignment_index}"
            reader_output = _run_role(
                runner,
                "reader",
                {
                    **base_payload,
                    "round_id": round_id,
                    "round_index": round_index,
                    "planner_output": planner_output,
                    "worker_assignment": assignment,
                    "worker_brief": str(assignment.get("worker_brief", "")),
                    "previous_judgement": (
                        previous_judgement.to_dict()
                        if previous_judgement is not None
                        else None
                    ),
                    "accepted_evidence_ids": list(accepted_evidence_ids),
                    "rejected_evidence_ids": list(rejected_evidence_ids),
                    "domain_state": store.to_run_state(),
                },
                run_dir=run_dir,
                role_outputs_dir=role_outputs_dir,
                store=store,
                run_id=config.run_id,
                output_name=reader_output_name,
            )
            role_outputs[reader_output_name] = reader_output
            import_result = _import_reader_output(
                store,
                registry,
                reader_output,
                created_by=f"codex-reader-{round_id}-{assignment_index}",
            )
            reader_source_materials = materializer.materialize_reader_output(
                store=store,
                registry=registry,
                reader_output=reader_output,
                import_result=import_result,
                run_dir=run_dir,
                run_id=config.run_id,
                topic=config.topic,
                round_id=round_id,
                assignment_index=assignment_index,
                assignment=assignment,
                created_by=f"codex-reader-{round_id}-{assignment_index}",
            )
            if reader_source_materials:
                source_materials.extend(reader_source_materials)
                round_source_materials.extend(reader_source_materials)
                _append_trace(
                    store,
                    run_id=config.run_id,
                    event_type="reader_source_materialized",
                    actor="codex_workflow",
                    target_type="SourceMaterial",
                    target_id=f"{round_id}-reader-{assignment_index}",
                    input_refs=list(import_result["accepted_evidence_ids"]),
                    output_refs=_source_material_output_refs(reader_source_materials),
                    summary="reader accepted evidence materialized into local artifacts",
                    payload={
                        "round_id": round_id,
                        "assignment_index": assignment_index,
                        "source_materials": reader_source_materials,
                    },
                )
            accepted_source_ids = _dedupe(
                [*accepted_source_ids, *import_result["accepted_source_ids"]]
            )
            rejected_source_ids = _dedupe(
                [*rejected_source_ids, *import_result["rejected_source_ids"]]
            )
            accepted_evidence_ids = _dedupe(
                [*accepted_evidence_ids, *import_result["accepted_evidence_ids"]]
            )
            rejected_evidence_ids = _dedupe(
                [*rejected_evidence_ids, *import_result["rejected_evidence_ids"]]
            )
            worker_report = _reader_worker_report(
                round_id=round_id,
                assignment_index=assignment_index,
                assignment=assignment,
                reader_output=reader_output,
                import_result=import_result,
                source_materials=reader_source_materials,
            )
            round_worker_reports.append(worker_report)
            all_worker_reports.append(worker_report)
            round_reader_outputs.append(reader_output)
        research_round.worker_report_ids = [
            str(report["worker_report_id"]) for report in round_worker_reports
        ]
        store.upsert_research_round(research_round)
        _append_trace(
            store,
            run_id=config.run_id,
            event_type="worker_reports_recorded",
            actor="codex_workflow",
            target_type="ResearchRound",
            target_id=round_id,
            input_refs=[*accepted_evidence_ids],
            output_refs=list(research_round.worker_report_ids),
            summary=f"Codex reader worker reports recorded for {round_id}",
            payload={"worker_reports": list(round_worker_reports)},
        )
        judge_output_name = f"{round_id}_judge"
        judge_output = _run_role(
            runner,
            "judge",
            {
                **base_payload,
                "round_id": round_id,
                "round_index": round_index,
                "planner_output": planner_output,
                "reader_outputs": round_reader_outputs,
                "worker_reports": round_worker_reports,
                "all_worker_reports": all_worker_reports,
                "accepted_source_ids": accepted_source_ids,
                "rejected_source_ids": rejected_source_ids,
                "accepted_evidence_ids": accepted_evidence_ids,
                "rejected_evidence_ids": rejected_evidence_ids,
                "source_materials": list(source_materials),
                "round_source_materials": list(round_source_materials),
                "previous_judgement": (
                    previous_judgement.to_dict()
                    if previous_judgement is not None
                    else None
                ),
                "domain_state": store.to_run_state(),
            },
            run_dir=run_dir,
            role_outputs_dir=role_outputs_dir,
            store=store,
            run_id=config.run_id,
            output_name=judge_output_name,
        )
        role_outputs[judge_output_name] = judge_output
        judgement = _import_judgement_output(
            store,
            judge_output,
            round_id=round_id,
            accepted_evidence_ids=accepted_evidence_ids,
        )
        repaired_plan = build_repaired_next_round_plan(
            judgement.next_round_plan,
            topic=config.topic,
            round_id=round_id,
            summary=judgement.rationale,
        )
        plan_assessment = assess_next_round_plan(repaired_plan)
        if repaired_plan != judgement.next_round_plan:
            judgement.next_round_plan = repaired_plan
            store.upsert_judgement_report(judgement)
        next_assignments = worker_assignments_from_judgement(
            judgement,
            topic=config.topic,
        )
        should_continue = (
            judgement.stop_or_continue == "continue"
            and round_index < max_rounds
            and bool(next_assignments)
        )
        stop_reason = None
        if not should_continue:
            stop_reason = _round_stop_reason(
                judgement=judgement,
                round_index=round_index,
                max_rounds=max_rounds,
                next_assignments=next_assignments,
            )
        research_round = ResearchRound(
            **{
                **research_round.to_dict(),
                "status": "judged" if should_continue else "stopped",
                "judgement_id": judgement.judgement_id,
                "next_round_plan": judgement.next_round_plan,
                "stop_reason": stop_reason,
                "updated_at": _now(),
            }
        )
        store.upsert_research_round(research_round)
        rounds.append(
            {
                **research_round.to_dict(),
                "judgement": judgement.to_dict(),
                "plan_assessment": {
                    "is_valid": plan_assessment.is_valid,
                    "errors": list(plan_assessment.errors),
                    "warnings": list(plan_assessment.warnings),
                },
                "worker_reports": list(round_worker_reports),
                "source_materials": list(round_source_materials),
            }
        )
        previous_judgement = judgement
        if not should_continue:
            break
        assignments = next_assignments
    if judgement is None:
        raise RuntimeError("Codex workflow produced no judgement")

    synthesizer_output = _run_role(
        runner,
        "synthesizer",
        {
            **base_payload,
            "rounds": rounds,
            "judgement": judgement.to_dict(),
            "accepted_evidence_ids": accepted_evidence_ids,
            "source_materials": list(source_materials),
            "domain_state": store.to_run_state(),
        },
        run_dir=run_dir,
        role_outputs_dir=role_outputs_dir,
        store=store,
        run_id=config.run_id,
    )
    role_outputs["synthesizer"] = synthesizer_output
    candidate = _import_candidate_output(
        store,
        synthesizer_output,
        accepted_evidence_ids=accepted_evidence_ids,
    )
    _append_trace(
        store,
        run_id=config.run_id,
        event_type="candidate_synthesized",
        actor="codex-synthesizer",
        target_type="CandidateDemand",
        target_id=candidate.candidate_id,
        input_refs=[judgement.judgement_id, *candidate.evidence_ids],
        output_refs=[candidate.candidate_id],
        summary=f"candidate synthesized by Codex role {candidate.candidate_id}",
        decision="candidate_demand",
        rationale=str(synthesizer_output.get("rationale", "")),
    )

    auditor_output = _run_role(
        runner,
        "auditor",
        {
            **base_payload,
            "rounds": rounds,
            "candidate": candidate.to_dict(),
            "judgement": judgement.to_dict(),
            "accepted_evidence_ids": accepted_evidence_ids,
            "source_materials": list(source_materials),
            "domain_state": store.to_run_state(),
        },
        run_dir=run_dir,
        role_outputs_dir=role_outputs_dir,
        store=store,
        run_id=config.run_id,
    )
    role_outputs["auditor"] = auditor_output
    audit = _import_audit_output(
        store,
        auditor_output,
        candidate_id=candidate.candidate_id,
        accepted_evidence_ids=accepted_evidence_ids,
    )
    audit_trace = _append_trace(
        store,
        run_id=config.run_id,
        event_type="audit_completed",
        actor="codex-auditor",
        target_type="AuditReport",
        target_id=audit.audit_id,
        input_refs=[candidate.candidate_id, judgement.judgement_id, *accepted_evidence_ids],
        output_refs=[audit.audit_id],
        summary=f"audit completed by Codex role {audit.audit_id}",
        decision=audit.conclusion,
        rationale=audit.comments,
    )

    reporter_payload = {
        **base_payload,
        "rounds": rounds,
        "candidate": candidate.to_dict(),
        "judgement": judgement.to_dict(),
        "audit": audit.to_dict(),
        "accepted_evidence_ids": accepted_evidence_ids,
        "rejected_evidence_ids": rejected_evidence_ids,
        "source_materials": list(source_materials),
        "domain_state": store.to_run_state(),
        "report_requirements": _report_requirements(),
    }
    reporter_output, report_quality, reporter_role_outputs = _run_reporter_with_quality_gate(
        runner,
        reporter_payload,
        run_dir=run_dir,
        role_outputs_dir=role_outputs_dir,
        store=store,
        run_id=config.run_id,
        max_rewrites=max(0, int(config.max_report_rewrites or 0)),
    )
    role_outputs.update(reporter_role_outputs)
    report = _import_report_output(
        store,
        reporter_output,
        candidate_id=candidate.candidate_id,
        audit=audit,
        audit_trace_id=audit_trace.domain_trace_id,
        accepted_evidence_ids=accepted_evidence_ids,
    )
    report_trace = _append_trace(
        store,
        run_id=config.run_id,
        event_type="report_generated",
        actor="codex-reporter",
        target_type="DemandReport",
        target_id=report.report_id,
        input_refs=[
            candidate.candidate_id,
            judgement.judgement_id,
            audit.audit_id,
            *report.evidence_ids,
        ],
        output_refs=[report.report_id],
        summary=f"report generated by Codex role {report.report_id}",
        decision=report.review_status,
    )
    if report_trace.domain_trace_id not in report.domain_trace_ids:
        report.domain_trace_ids.append(report_trace.domain_trace_id)
    published = publish_report(store, report_id=report.report_id, output_dir=run_dir)
    _append_trace(
        store,
        run_id=config.run_id,
        event_type="report_published",
        actor="codex_workflow",
        target_type="DemandReport",
        target_id=report.report_id,
        input_refs=[report.report_id],
        output_refs=[str(published.report_md_path), str(published.manifest_path)],
        summary="independent Codex report published",
    )

    round_summary_path = run_dir / "round_summary.json"
    domain_path = run_dir / "domain.jsonl"
    trace_path = run_dir / "trace.jsonl"
    summary = {
        "run_id": config.run_id,
        "mode": "codex",
        "execution": "independent_codex_workflow",
        "topic": config.topic,
        "source_strategy": strategy.to_dict(),
        "roles": list(ROLE_ORDER),
        "round_count": round_count,
        "rounds": rounds,
        "worker_reports": all_worker_reports,
        "accepted_source_ids": accepted_source_ids,
        "rejected_source_ids": rejected_source_ids,
        "accepted_evidence_ids": accepted_evidence_ids,
        "rejected_evidence_ids": rejected_evidence_ids,
        "source_materials": source_materials,
        "judgement": judgement.to_dict(),
        "candidate": candidate.to_dict(),
        "audit": audit.to_dict(),
        "report": report.to_dict(),
        "report_quality": report_quality,
        "role_output_paths": {
            name: str(role_outputs_dir / f"{name}.json") for name in role_outputs
        },
        "trace_event_count": len(store.trace_events),
        "report_md_path": str(published.report_md_path),
        "report_manifest_path": str(published.manifest_path),
    }
    round_summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    store.export_jsonl(domain_path)
    _write_trace_jsonl(store, trace_path)
    return CodexWorkflowResult(
        run_id=config.run_id,
        run_dir=run_dir,
        source_strategy_id=strategy.strategy_id,
        round_summary_path=round_summary_path,
        domain_path=domain_path,
        trace_path=trace_path,
        report_path=published.report_md_path,
    )


def _run_role(
    runner: RoleRunner,
    role: str,
    payload: dict[str, object],
    *,
    run_dir: Path,
    role_outputs_dir: Path,
    store: DomainStore,
    run_id: str,
    output_name: str | None = None,
) -> dict[str, object]:
    output = runner.run_role(role, payload, run_dir=run_dir)
    if not isinstance(output, dict):
        raise ValueError(f"role {role} output must be a JSON object")
    file_stem = output_name or role
    (role_outputs_dir / f"{file_stem}.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _append_trace(
        store,
        run_id=run_id,
        event_type="codex_role_completed",
        actor=f"codex-{role}",
        target_type="CodexRoleOutput",
        target_id=file_stem,
        output_refs=[str(role_outputs_dir / f"{file_stem}.json")],
        summary=f"Codex role completed: {file_stem}",
        payload={"role": role, "output_name": file_stem},
    )
    return output


def _source_materializer_for_run(
    *,
    role_runner: RoleRunner | None,
    source_materializer: SourceMaterializer | None,
) -> SourceMaterializer:
    if source_materializer is not None:
        return source_materializer
    if role_runner is None:
        return DefaultSourceMaterializer()
    return _NullSourceMaterializer()


def _run_tool_sync(tool: Any, call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
    return asyncio.run(tool.execute(call, ctx))


def _looks_like_download_url(url: str) -> bool:
    path = str(url).split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith((".pdf", ".doc", ".docx", ".txt"))


def _source_material_id(evidence_id: str, ref: str) -> str:
    digest = hashlib.sha256(f"{evidence_id}:{ref}".encode("utf-8")).hexdigest()[:12]
    return f"mat-{digest}"


def _failed_source_material(
    *,
    evidence_id: str,
    source_id: str,
    url: str,
    error: str,
) -> dict[str, object]:
    return {
        "material_id": _source_material_id(evidence_id, url or source_id),
        "evidence_id": evidence_id,
        "source_id": source_id,
        "url": url,
        "artifact_ref": "",
        "simplified_ref": "",
        "matched_source_location": "",
        "read_excerpt": "",
        "status": "failed",
        "error": _clip_text(error, 500),
    }


def _source_material_output_refs(source_materials: list[dict[str, object]]) -> list[str]:
    refs: list[str] = []
    for material in source_materials:
        for key in ("material_id", "artifact_ref", "simplified_ref", "matched_source_location"):
            value = str(material.get(key, "")).strip()
            if value:
                refs.append(value)
    return _dedupe(refs)


def _artifact_paragraphs(artifacts: ArtifactStore, ref: str) -> list[str]:
    try:
        text = artifacts.get_text(ref)
    except KeyError:
        return []
    return [item.strip() for item in text.split("\n\n") if item.strip()]


def _best_evidence_paragraph(
    evidence: EvidenceCard,
    paragraphs: list[str],
) -> tuple[int, str] | None:
    if not paragraphs:
        return None
    probes = [
        str(evidence.excerpt or "").strip(),
        str(evidence.claim or "").strip(),
        str(evidence.evidence_summary or "").strip(),
    ]
    probes = [probe for probe in probes if probe]
    for index, paragraph in enumerate(paragraphs):
        if any(probe and (probe in paragraph or paragraph in probe) for probe in probes):
            return index, paragraph
    query = " ".join(probes)
    if not query:
        return None
    scored = [
        (_character_overlap_score(query, paragraph), index, paragraph)
        for index, paragraph in enumerate(paragraphs)
    ]
    score, index, paragraph = max(scored, key=lambda item: item[0])
    if score < 0.42:
        return None
    return index, paragraph


def _character_overlap_score(left: str, right: str) -> float:
    left_chars = _evidence_chars(left)
    right_chars = _evidence_chars(right)
    if not left_chars or not right_chars:
        return 0.0
    return len(left_chars & right_chars) / max(1, len(left_chars))


def _evidence_chars(text: str) -> set[str]:
    return {
        char
        for char in re.sub(r"\s+", "", text)
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    }


def _clip_text(text: object, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _initial_worker_assignments(
    planner_output: dict[str, object],
    *,
    topic: str,
) -> list[dict[str, object]]:
    tasks = [
        dict(item)
        for item in list(planner_output.get("reader_tasks") or [])
        if isinstance(item, dict)
    ]
    if not tasks:
        tasks = [
            {
                "task_id": "reader-task-1",
                "objective": f"围绕“{topic}”查找白名单正文证据",
                "queries": [topic],
                "completion_check": "新增白名单正文 EvidenceCard，或说明白名单路线耗尽",
            }
        ]
    assignments: list[dict[str, object]] = []
    for index, task in enumerate(tasks, start=1):
        task_id = str(task.get("task_id") or f"reader-task-{index}").strip()
        objective = str(task.get("objective") or topic).strip()
        queries = _task_queries(task, fallback=topic)
        query_revisions = [
            {"query": query, "rationale": "planner reader task"}
            for query in queries
        ]
        worker_brief = str(task.get("worker_brief") or "").strip()
        if not worker_brief:
            worker_brief = (
                f"调查任务 {task_id}：{objective}。优先白名单正文，"
                f"使用 query：{'；'.join(queries)}。"
                "只从正文/PDF/TXT 创建 SourceRecord 和 EvidenceCard；"
                "证据足够或路线耗尽时停止。"
            )
        assignments.append(
            {
                "task_id": task_id,
                "objective": objective,
                "routing_hint": str(task.get("routing_hint", "same_source_followup")),
                "source_scope": str(task.get("source_scope", "whitelist_first")),
                "input_refs": {
                    "worker_report_ids": [],
                    "evidence_ids": [],
                    "lead_ids": [],
                },
                "query_revisions": query_revisions,
                "completion_check": str(
                    task.get("completion_check")
                    or "新增白名单正文 EvidenceCard，或说明 route/query 已耗尽"
                ),
                "worker_brief": worker_brief,
            }
        )
    return assignments


def _reader_worker_report(
    *,
    round_id: str,
    assignment_index: int,
    assignment: dict[str, object],
    reader_output: dict[str, object],
    import_result: dict[str, list[str]],
    source_materials: list[dict[str, object]],
) -> dict[str, object]:
    task_id = str(assignment.get("task_id") or f"reader-task-{assignment_index}")
    worker_report_id = f"{round_id}-{task_id}-reader-{assignment_index}"
    findings = [str(item) for item in list(reader_output.get("findings") or [])]
    open_questions = [
        str(item) for item in list(reader_output.get("open_questions") or [])
    ]
    remaining_gaps = [
        str(item) for item in list(reader_output.get("remaining_gaps") or [])
    ]
    risks = [str(item) for item in list(reader_output.get("risks") or [])]
    accepted_evidence = list(import_result["accepted_evidence_ids"])
    return {
        "worker_report_id": worker_report_id,
        "report_id": worker_report_id,
        "round_id": round_id,
        "role": "reader",
        "task_id": task_id,
        "task_brief": str(assignment.get("worker_brief") or assignment.get("objective") or ""),
        "objective": str(assignment.get("objective") or ""),
        "findings": findings,
        "partial_findings": findings,
        "open_questions": open_questions,
        "remaining_gaps": remaining_gaps,
        "suggested_next_routes": list(reader_output.get("suggested_next_routes") or []),
        "need_more_sources": bool(reader_output.get("need_more_sources", not accepted_evidence)),
        "stop_reason": str(
            reader_output.get("stop_reason")
            or ("evidence_sufficient" if accepted_evidence else "route_failed")
        ),
        "risk_or_conflict": risks,
        "accepted_source_ids": list(import_result["accepted_source_ids"]),
        "rejected_source_ids": list(import_result["rejected_source_ids"]),
        "accepted_evidence_ids": accepted_evidence,
        "rejected_evidence_ids": list(import_result["rejected_evidence_ids"]),
        "evidence_refs": accepted_evidence,
        "new_evidence_cards": accepted_evidence,
        "source_materials": list(source_materials),
    }


def _task_queries(task: dict[str, object], *, fallback: str) -> list[str]:
    rows: list[str] = []
    for key in ("queries", "query_revisions"):
        value = task.get(key)
        if not value:
            continue
        for item in list(value if isinstance(value, list) else [value]):
            if isinstance(item, dict):
                text = str(item.get("query", "")).strip()
            else:
                text = str(item).strip()
            if text:
                rows.append(text)
    return _dedupe(rows or [fallback])


def _assignment_input_refs(assignment: dict[str, object]) -> list[str]:
    refs: list[str] = []
    input_refs = assignment.get("input_refs", {})
    if not isinstance(input_refs, dict):
        return refs
    for key in ("worker_report_ids", "evidence_ids", "lead_ids"):
        refs.extend(str(item) for item in list(input_refs.get(key) or []) if str(item))
    return refs


def _round_stop_reason(
    *,
    judgement: JudgementReport,
    round_index: int,
    max_rounds: int,
    next_assignments: list[dict[str, object]],
) -> str:
    if judgement.stop_or_continue == "stop":
        return "judge_stop"
    if judgement.stop_or_continue == "needs_human_steer":
        return "needs_human_steer"
    if round_index >= max_rounds:
        return "max_rounds"
    if not next_assignments:
        return "no_executable_worker_assignments"
    return "stopped"


def _run_reporter_with_quality_gate(
    runner: RoleRunner,
    payload: dict[str, object],
    *,
    run_dir: Path,
    role_outputs_dir: Path,
    store: DomainStore,
    run_id: str,
    max_rewrites: int,
) -> tuple[dict[str, object], dict[str, object], dict[str, dict[str, object]]]:
    outputs: dict[str, dict[str, object]] = {}
    attempt = 1
    reporter_output = _run_role(
        runner,
        "reporter",
        payload,
        run_dir=run_dir,
        role_outputs_dir=role_outputs_dir,
        store=store,
        run_id=run_id,
        output_name="reporter",
    )
    outputs["reporter"] = reporter_output
    quality = _assess_report_quality(reporter_output)
    while quality["status"] != "passed" and attempt <= max_rewrites:
        _append_trace(
            store,
            run_id=run_id,
            event_type="report_quality_rewrite_requested",
            actor="codex_workflow",
            target_type="CodexRoleOutput",
            target_id=f"reporter_attempt_{attempt}",
            input_refs=[str(item) for item in list(reporter_output.get("evidence_ids") or [])],
            output_refs=[],
            summary="report quality gate requested reporter rewrite",
            decision=str(quality["status"]),
            rationale="; ".join(str(item) for item in list(quality.get("issues") or [])),
            payload={"quality": quality},
        )
        rewrite_name = f"reporter_rewrite_{attempt}"
        reporter_output = _run_role(
            runner,
            "reporter",
            {
                **payload,
                "previous_report_output": reporter_output,
                "report_quality_feedback": quality,
            },
            run_dir=run_dir,
            role_outputs_dir=role_outputs_dir,
            store=store,
            run_id=run_id,
            output_name=rewrite_name,
        )
        outputs[rewrite_name] = reporter_output
        attempt += 1
        quality = _assess_report_quality(reporter_output)
    quality["attempts"] = attempt
    return reporter_output, quality, outputs


def _assess_report_quality(output: dict[str, object]) -> dict[str, object]:
    body = str(output.get("body", "")).strip()
    issues: list[str] = []
    warnings: list[str] = []
    if len(body) < 40:
        issues.append("report body is too short for a reviewable demand report")
    if not _has_markdown_heading(body):
        issues.append("report body must use markdown sections")
    missing_sections = [
        keyword for keyword in REPORT_SECTION_KEYWORDS if keyword not in body
    ]
    if missing_sections:
        warnings.append(
            "report body is missing recommended sections: "
            + ", ".join(missing_sections)
        )
    evidence_ids = [str(item) for item in list(output.get("evidence_ids") or []) if str(item)]
    if not evidence_ids:
        issues.append("report has no accepted evidence_ids")
    return {
        "status": "passed" if not issues else "needs_rewrite",
        "issues": issues,
        "warnings": warnings,
        "missing_recommended_sections": missing_sections,
    }


def _has_markdown_heading(body: str) -> bool:
    return any(line.lstrip().startswith("#") for line in body.splitlines())


def _report_requirements() -> dict[str, object]:
    return {
        "language": "zh-CN",
        "minimum_shape": [
            "结论摘要",
            "场景与压力",
            "能力缺口拆解",
            "证据矩阵",
            "审计结论与限制",
            "后续验证计划",
        ],
        "quality_gate": [
            "不得只写短结论",
            "核心结论必须引用 accepted evidence ids",
            "必须写出证据限制和待验证问题",
            "needs_revision/watchlist/rejected 必须降级表达",
        ],
    }


def _import_reader_output(
    store: DomainStore,
    registry: SourceRegistry,
    output: dict[str, object],
    *,
    created_by: str,
) -> dict[str, list[str]]:
    accepted_source_ids: list[str] = []
    rejected_source_ids: list[str] = []
    accepted_evidence_ids: list[str] = []
    rejected_evidence_ids: list[str] = []
    source_rows = [
        dict(item)
        for item in list(output.get("source_records") or [])
        if isinstance(item, dict)
    ]
    evidence_rows = [
        dict(item)
        for item in list(output.get("evidence_cards") or [])
        if isinstance(item, dict)
    ]
    for row in source_rows:
        source_id = str(row.get("source_id", "")).strip()
        url = str(row.get("url_or_path", "")).strip()
        entry = registry.match(url)
        if not source_id or entry is None:
            if source_id:
                rejected_source_ids.append(source_id)
            continue
        store.upsert_source(
            SourceRecord(
                source_id=source_id,
                title=str(row.get("title", "")).strip() or entry.source_name,
                source_name=entry.source_name,
                source_tier=entry.source_tier,
                source_type=entry.source_type,
                publish_time=_parse_datetime_or_none(row.get("publish_time")),
                url_or_path=url,
                summary_text=_optional_str(row.get("summary_text")),
                summary_source=str(row.get("summary_source", "codex")),
                collection_decision=str(
                    row.get("collection_decision", "use_as_evidence")
                ),
                author_or_org=_optional_str(row.get("author_or_org")),
                is_repost=_optional_bool(row.get("is_repost")),
                original_source=_optional_str(row.get("original_source")),
                institutional_stance=_optional_str(row.get("institutional_stance")),
                created_at=_now(),
                updated_at=_now(),
            )
        )
        accepted_source_ids.append(source_id)
    for row in evidence_rows:
        evidence_id = str(row.get("evidence_id", "")).strip()
        source_id = str(row.get("source_id", "")).strip()
        if not evidence_id or source_id not in store.sources:
            if evidence_id:
                rejected_evidence_ids.append(evidence_id)
            continue
        store.upsert_evidence(
            EvidenceCard(
                evidence_id=evidence_id,
                source_id=source_id,
                claim=str(row.get("claim", "")).strip(),
                evidence_summary=str(row.get("evidence_summary", "")).strip(),
                excerpt=_optional_str(row.get("excerpt")),
                source_location=str(row.get("source_location", "")).strip(),
                evidence_assessment=str(row.get("evidence_assessment", "strong")),
                created_by=created_by,
                created_at=_now(),
            )
        )
        accepted_evidence_ids.append(evidence_id)
    return {
        "accepted_source_ids": _dedupe(accepted_source_ids),
        "rejected_source_ids": _dedupe(rejected_source_ids),
        "accepted_evidence_ids": _dedupe(accepted_evidence_ids),
        "rejected_evidence_ids": _dedupe(rejected_evidence_ids),
    }


def _import_judgement_output(
    store: DomainStore,
    output: dict[str, object],
    *,
    round_id: str,
    accepted_evidence_ids: list[str],
) -> JudgementReport:
    judgement = JudgementReport(
        judgement_id=str(output.get("judgement_id", "judge-codex")),
        round_id=str(output.get("round_id", round_id)) or round_id,
        consensus_points=_judgement_items(
            output.get("consensus_points"),
            accepted_evidence_ids=accepted_evidence_ids,
            require_support=True,
        ),
        contradictions=_judgement_items(
            output.get("contradictions"),
            accepted_evidence_ids=accepted_evidence_ids,
        ),
        partial_coverage=_judgement_items(
            output.get("partial_coverage"),
            accepted_evidence_ids=accepted_evidence_ids,
        ),
        unique_insights=_judgement_items(
            output.get("unique_insights"),
            accepted_evidence_ids=accepted_evidence_ids,
        ),
        blind_spots=_judgement_items(
            output.get("blind_spots"),
            accepted_evidence_ids=accepted_evidence_ids,
        ),
        evidence_strength_map={
            evidence_id: str(strength)
            for evidence_id, strength in dict(
                output.get("evidence_strength_map") or {}
            ).items()
            if evidence_id in accepted_evidence_ids
        },
        next_round_plan=dict(output.get("next_round_plan") or {}),
        stop_or_continue=str(output.get("stop_or_continue", "stop")),
        rationale=str(output.get("rationale", "")),
        created_at=_now(),
    )
    store.upsert_judgement_report(judgement)
    return judgement


def _import_candidate_output(
    store: DomainStore,
    output: dict[str, object],
    *,
    accepted_evidence_ids: list[str],
) -> CandidateDemand:
    evidence_ids = _accepted_refs(output.get("evidence_ids"), accepted_evidence_ids)
    if not evidence_ids:
        raise ValueError("Codex synthesizer output has no accepted evidence_ids")
    candidate = CandidateDemand(
        candidate_id=str(output.get("candidate_id", "cand-codex")),
        title=str(output.get("title", "")).strip(),
        demand_statement=str(output.get("demand_statement", "")).strip(),
        status="candidate_demand",
        evidence_ids=evidence_ids,
        open_questions=[str(item) for item in list(output.get("open_questions") or [])],
        solution_signals=[
            str(item) for item in list(output.get("solution_signals") or [])
        ],
        created_by="codex-synthesizer",
        created_at=_now(),
        updated_at=_now(),
    )
    store.upsert_candidate(candidate)
    return candidate


def _import_audit_output(
    store: DomainStore,
    output: dict[str, object],
    *,
    candidate_id: str,
    accepted_evidence_ids: list[str],
) -> AuditReport:
    scorecard = dict(output.get("scorecard") or {})
    support = dict(scorecard.get("evidence_support") or {})
    reviews = {
        evidence_id: dict(review)
        for evidence_id, review in dict(support.get("evidence_reviews") or {}).items()
        if evidence_id in accepted_evidence_ids and isinstance(review, dict)
    }
    support["evidence_reviews"] = reviews
    scorecard["evidence_support"] = support
    audit = AuditReport(
        audit_id=str(output.get("audit_id", "audit-codex")),
        candidate_id=candidate_id,
        conclusion=str(output.get("conclusion", "needs_revision")),
        scorecard=scorecard,
        comments=str(output.get("comments", "")),
        required_rework=[str(item) for item in list(output.get("required_rework") or [])],
        created_by="codex-auditor",
        created_at=_now(),
    )
    store.append_audit(audit)
    return audit


def _import_report_output(
    store: DomainStore,
    output: dict[str, object],
    *,
    candidate_id: str,
    audit: AuditReport,
    audit_trace_id: str,
    accepted_evidence_ids: list[str],
) -> DemandReport:
    evidence_ids = _accepted_refs(output.get("evidence_ids"), accepted_evidence_ids)
    if not evidence_ids:
        evidence_ids = list(accepted_evidence_ids)
    store.update_candidate_status(
        candidate_id,
        "demand_report",
        "independent Codex workflow reached report gate",
        "codex_workflow",
    )
    base_report = DemandReport(
        report_id=str(output.get("report_id", "report-codex")),
        candidate_id=candidate_id,
        title=str(output.get("title", "")).strip(),
        body=str(output.get("body", "")).strip(),
        evidence_ids=evidence_ids,
        audit_id=audit.audit_id,
        domain_trace_ids=[audit_trace_id],
        created_at=_now(),
        review_status=_report_status_from_audit(audit),
    )
    body_with_audit = render_demand_report(store, base_report)
    report = DemandReport(
        **{
            **base_report.to_dict(),
            "body": body_with_audit,
            "created_at": base_report.created_at,
        }
    )
    return store.append_demand_report(report)


def _report_status_from_audit(audit: AuditReport) -> str:
    evidence_support = dict(audit.scorecard.get("evidence_support") or {})
    recommended = str(evidence_support.get("recommended_report_status", "")).strip()
    if recommended in {"review_ready", "needs_revision", "watchlist", "rejected"}:
        return recommended
    conclusion = audit.conclusion.strip().lower()
    if conclusion in {"approved", "pass", "通过"}:
        return "review_ready"
    if conclusion == "needs_revision":
        return "needs_revision"
    if conclusion == "rejected":
        return "rejected"
    if conclusion == "watchlist":
        return "watchlist"
    return "needs_revision"


def _judgement_items(
    values: object,
    *,
    accepted_evidence_ids: list[str],
    require_support: bool = False,
) -> list[JudgementItem]:
    rows: list[JudgementItem] = []
    for item in list(values or []):
        if not isinstance(item, dict):
            continue
        evidence_ids = _accepted_refs(item.get("evidence_ids"), accepted_evidence_ids)
        lead_ids = [str(value) for value in list(item.get("lead_ids") or [])]
        if require_support and not evidence_ids and not lead_ids:
            continue
        worker_report_ids = [
            str(value) for value in list(item.get("worker_report_ids") or [])
        ] or ["codex-reader"]
        rows.append(
            JudgementItem(
                text=str(item.get("text", "")).strip(),
                worker_report_ids=worker_report_ids,
                evidence_ids=evidence_ids,
                lead_ids=lead_ids,
            )
        )
    return rows


def _role_prompt(role: str, payload: dict[str, object]) -> str:
    role_instructions = _role_instructions(role)
    return (
        f"You are the demand-discovery {role} role. "
        "Return exactly one JSON object matching the requested role output. "
        "Use Codex native web search when useful, but prefer whitelisted sources "
        "and preserve query/url/evidence lineage. Do not include markdown fences.\n\n"
        "# Role Instructions\n"
        f"{role_instructions}\n\n"
        "# Input JSON\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}\n\n"
        "# Required JSON Shape\n"
        f"{json.dumps(_role_contract(role), ensure_ascii=False, indent=2, sort_keys=True)}\n\n"
        "# Output Rule\n"
        "Return JSON only."
    )


def _role_contract(role: str) -> dict[str, object]:
    if role == "planner":
        return {
            "research_directions": ["short direction"],
            "reader_tasks": [
                {
                    "task_id": "reader-task-1",
                    "objective": "what evidence gap to investigate",
                    "queries": ["query strings, preferably site: whitelisted hosts"],
                    "source_scope": "whitelist_first",
                    "completion_check": "what body evidence or exhaustion condition ends the task",
                    "worker_brief": "natural-language instruction for the reader worker",
                }
            ],
        }
    if role == "reader":
        return {
            "source_records": [
                {
                    "source_id": "src-short-stable-id",
                    "title": "article/report title",
                    "source_name": "whitelist source name",
                    "source_tier": "A or B",
                    "source_type": "official|journal|thinktank|defense_media",
                    "publish_time": "YYYY-MM-DD or empty",
                    "url_or_path": "exact public URL",
                    "summary_text": "short source summary",
                    "summary_source": "codex_websearch",
                    "collection_decision": "use_as_evidence",
                }
            ],
            "evidence_cards": [
                {
                    "evidence_id": "ev-short-stable-id",
                    "source_id": "src-short-stable-id",
                    "claim": "one evidence-backed claim",
                    "evidence_summary": "why the body supports the claim",
                    "excerpt": "short quoted or close paraphrased evidence span",
                    "source_location": "text:url-or-page#para:1",
                    "evidence_assessment": "strong|direct|partial|adjacent|weak",
                }
            ],
            "findings": ["concise evidence-backed finding"],
            "open_questions": ["remaining evidence gap"],
            "evidence_ready_for_judge": True,
            "stop_reason": "evidence_sufficient|whitelist_exhausted|route_failed|needs_open_search|budget_wrapup",
            "remaining_gaps": ["missing direct evidence or none"],
            "suggested_next_routes": ["specific next route or none"],
            "need_more_sources": False,
            "risks": ["source limitation or none"],
        }
    if role == "judge":
        return {
            "judgement_id": "judge-codex-1",
            "round_id": "round-1",
            "consensus_points": [
                {
                    "text": "consensus point",
                    "worker_report_ids": ["reader-task-1"],
                    "evidence_ids": ["accepted evidence ids only"],
                    "lead_ids": [],
                }
            ],
            "contradictions": [],
            "partial_coverage": [],
            "unique_insights": [],
            "blind_spots": [],
            "evidence_strength_map": {"evidence_id": "strong"},
            "next_round_plan": {
                "plan_version": 1,
                "summary": "stop or continue rationale",
                "controller_tasks": [
                    {
                        "task_id": "followup-1",
                        "objective": "gap to close",
                        "gap_type": "missing_direct_evidence|partial_only|contradiction|source_gap|route_failed|open_search_candidate|human_profile_needed|report_ready_with_limits",
                        "routing_hint": "same_source_followup|different_whitelist_source|open_search_candidate|human_profile_needed|stop_for_report",
                        "source_scope": "whitelist_first|whitelist_only|open_web_after_whitelist_exhausted|human_profile_required",
                        "input_refs": {
                            "worker_report_ids": ["required worker report ids"],
                            "evidence_ids": ["accepted evidence ids only"],
                            "lead_ids": [],
                        },
                        "query_revisions": [
                            {
                                "query": "specific query",
                                "rationale": "why this query closes the gap",
                            }
                        ],
                        "completion_check": "how the next reader knows to stop",
                    }
                ],
                "worker_briefs": {
                    "followup-1": "natural-language brief matching controller task"
                },
                "remaining_open_questions": [],
                "stop_candidate_reason": "why report can proceed",
            },
            "stop_or_continue": "stop",
            "rationale": "brief judgement rationale",
        }
    if role == "synthesizer":
        return {
            "candidate_id": "cand-codex-1",
            "title": "candidate demand title",
            "demand_statement": "scenario + pressure + capability gap + uncertainty",
            "evidence_ids": ["accepted evidence ids only"],
            "open_questions": ["remaining uncertainty"],
            "solution_signals": ["optional solution or technical clue"],
            "rationale": "why this is a candidate demand",
        }
    if role == "auditor":
        return {
            "audit_id": "audit-codex-1",
            "candidate_id": "candidate id",
            "conclusion": "approved|needs_revision|rejected",
            "comments": "audit explanation",
            "required_rework": [],
            "scorecard": {
                "evidence_support": {
                    "verdict": "pass|doubt|fail",
                    "reason": "overall evidence support reason",
                    "recommended_report_status": "review_ready|needs_revision|watchlist|rejected",
                    "recheck_conditions": [],
                    "evidence_reviews": {
                        "evidence_id": {
                            "evidence_id": "evidence_id",
                            "support_level": "direct|partial|adjacent|weak|irrelevant|unassessed",
                            "support_type": "explicit_demand|inferred_gap|context_only|counter_evidence|irrelevant",
                            "used_for_core": True,
                            "reason": "support reason",
                            "missing_link": "",
                        }
                    },
                },
                "evidence_supports_candidate": {
                    "verdict": "pass|doubt|fail",
                    "reason": "rubric reason",
                },
                "core_conclusion_supported": {
                    "verdict": "pass|doubt|fail",
                    "reason": "rubric reason",
                },
            },
        }
    if role == "reporter":
        return {
            "report_id": "report-codex-1",
            "candidate_id": "candidate id",
            "title": "report title",
            "body": (
                "Chinese Markdown report with sections: 结论摘要, 场景与压力, "
                "能力缺口拆解, 证据矩阵, 审计结论与限制, 后续验证计划"
            ),
            "evidence_ids": ["accepted evidence ids only"],
        }
    return {}


def _role_instructions(role: str) -> str:
    path = _role_instruction_path(role)
    if path is not None and path.exists():
        return _strip_frontmatter(path.read_text(encoding="utf-8")).strip()
    return f"# {role}\nFollow the workflow rules and JSON contract exactly."


def _role_instruction_path(role: str) -> Path | None:
    base = Path(__file__).resolve().parent
    if role in AGENT_PROMPT_ROLES:
        return base / "workers" / "agents" / f"{role}.md"
    codex_role = base / "workers" / "codex_roles" / f"{role}.md"
    if codex_role.exists():
        return codex_role
    return None


def _strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :])
    return text


def _codex_command(config: CodexWorkflowConfig, output_path: Path) -> list[str]:
    executable = shutil.which("codex") or "codex"
    command = [executable]
    if config.enable_web_search:
        command.append("--search")
    command.extend(
        [
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "-C",
            str(config.project_root or Path.cwd()),
            "--model",
            config.codex_model,
            "-c",
            f'model_reasoning_effort="{config.reasoning_effort}"',
            "--output-last-message",
            str(output_path),
            "-",
        ]
    )
    return command


def _codex_env(config: CodexWorkflowConfig) -> dict[str, str]:
    env = dict(os.environ)
    if config.codex_home is not None:
        env["CODEX_HOME"] = str(config.codex_home)
    return env


def _extract_json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        last_marker = stripped.rfind("```")
        if first_newline >= 0 and last_marker > first_newline:
            stripped = stripped[first_newline:last_marker].strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        payload, _ = decoder.raw_decode(stripped[index:])
        if isinstance(payload, dict):
            return payload
    raise ValueError("Codex role output contains no JSON object")


def _append_trace(
    store: DomainStore,
    *,
    run_id: str,
    event_type: str,
    actor: str,
    target_type: str,
    target_id: str,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
    summary: str,
    decision: str | None = None,
    rationale: str | None = None,
    payload: dict[str, Any] | None = None,
) -> DomainTraceEvent:
    return store.append_trace(
        DomainTraceEvent(
            domain_trace_id=f"dt-{uuid4().hex}",
            trace_id=run_id,
            event_type=event_type,
            actor=actor,
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


def _write_trace_jsonl(store: DomainStore, path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for event in store.trace_events:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _whitelist_payload(registry: SourceRegistry) -> list[dict[str, object]]:
    return [
        {
            "source_name": source.source_name,
            "source_tier": source.source_tier,
            "source_type": source.source_type,
            "hosts": list(source.hosts),
            "path_prefixes": list(source.path_prefixes),
            "entry_urls": list(source.entry_urls),
            "content_languages": list(source.content_languages),
            "planned_use": "prefer in reader search queries and evidence import",
        }
        for source in registry.sources
    ]


def _workflow_rules() -> list[str]:
    return [
        "白名单内正文证据才可成为 SourceRecord/EvidenceCard。",
        "白名单外来源只能作为 rejected or suggested_source，不可进入正式 evidence_ids。",
        "EvidenceCard 必须来自正文段落、PDF/TXT/document body，不可来自 search/listing/snippet。",
        "报告必须显式区分证据支撑、限制和待验证问题。",
    ]


def _accepted_refs(values: object, accepted: list[str]) -> list[str]:
    accepted_set = set(accepted)
    return _dedupe([str(item) for item in list(values or []) if str(item) in accepted_set])


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


def _parse_datetime_or_none(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    return bool(value)


def _now() -> datetime:
    return datetime.now(timezone.utc)
