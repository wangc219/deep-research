from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import NoResultFound

from equipment_deep_research.application.dto import CreateRunCommand, UpdateRunCommand
from equipment_deep_research.application.run_service import (
    InvalidRunTransition,
    PERMANENTLY_DELETABLE_STATUSES,
    ResearchApplicationService,
    RunNotFoundError,
)
from equipment_deep_research.application.factory import build_application_service
from equipment_deep_research.application.worker_pool_config import write_worker_capacity
from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.orchestration.blueprints import (
    BRANCH_BLUEPRINTS,
    WINNING_STEP_DEFINITIONS,
    build_discovery_blueprint,
    winning_step_modes,
)
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.orchestration.coverage import load_preset_policy
from equipment_deep_research.orchestration.capability_portrait import (
    complete_operational_process,
    normalize_capability_problem,
    normalize_verification_plan,
    primary_equipment_form_title,
    strip_schema_placeholders,
)
from equipment_deep_research.harness.event_bus import sanitize_runtime_payload
from equipment_deep_research.query_library.api import create_router as create_query_library_router
from equipment_deep_research.query_library.factory import (
    build_service as build_query_library_service,
    default_seed_manifest,
)
from equipment_deep_research.query_library.models import QueryLibraryError
from equipment_deep_research.query_library.service import QueryLibraryService


_KEY_INTERACTION_EVENT_TYPES = frozenset(
    {
        "run_started",
        "run_failed",
        "run_recovered",
        "discovery_meta_loop_evaluated",
        "baseline_pipeline_started",
        "baseline_discovery_started",
        "baseline_discovery_lane_started",
        "baseline_discovery_lane_completed",
        "baseline_discovery_lane_limited",
        "baseline_discovery_completed",
        "baseline_model_queue_started",
        "baseline_model_call_started",
        "baseline_model_call_progress",
        "baseline_model_call_completed",
        "baseline_analysis_started",
        "baseline_analysis_completed",
        "baseline_materialization_progress",
        "baseline_wave_started",
        "baseline_wave_completed",
        "agent_task_delegated",
        "agent_harness_completed",
        "baseline_agent_completed",
        "baseline_agents_summarized",
        "discovery_convergence_completed",
        "discovery_convergence_reused",
        "winning_subagent_completed",
        "winning_model_queue_started",
        "winning_model_call_started",
        "winning_model_call_progress",
        "winning_model_call_completed",
        "winning_model_result_reused",
        "swarm_planned",
        "specialist_recruitment_planned",
        "specialist_spawned",
        "specialist_session_started",
        "specialist_session_completed",
        "specialist_completed",
        "specialist_pruned",
        "winning_mission_graph_planned",
        "winning_agent_instance_recruited",
        "winning_agent_instance_ready",
        "winning_agent_session_started",
        "winning_agent_waiting",
        "winning_agent_session_completed",
        "winning_agent_instance_failed",
        "winning_agent_instance_cancelled",
        "winning_pre_generation_angle_portfolio_planned",
        "winning_s3_active_agents_materialized",
        "winning_s3_first_pass_self_admission_completed",
        "winning_s3_empty_angle_reallocated",
        "winning_candidate_branch_created",
        "winning_semantic_clustering_started",
        "winning_semantic_clustering_completed",
        "winning_candidate_competition_converged",
        "winning_specialized_seed_recovered",
        "winning_specialized_seed_empty",
        "winning_candidate_ledger_frozen",
        "winning_contribution_queued",
        "winning_contribution_rejected",
        "winning_contribution_rebase_required",
        "winning_contribution_merged",
        "winning_portfolio_merge_completed",
        "winning_quality_judge_recruited",
        "winning_quality_judge_started",
        "winning_quality_judge_assessed",
        "winning_quality_judge_completed",
        "winning_quality_judge_failed",
        "winning_quality_repair_planned",
        "winning_quality_repair_completed",
        "winning_quality_repair_failed",
        "hypothesis_created",
        "hypothesis_merged",
        "hypothesis_rejected",
        "swarm_gate_evaluated",
        "promotion_candidate_created",
        "winning_inner_loop_evaluated",
        "winning_middle_loop_evaluated",
        "winning_outer_loop_evaluated",
        "winning_reasoning_step_completed",
        "winning_stage_completed",
        "recall_requested",
        "recall_task_completed",
        "coverage_recomputed_after_recall",
        "winning_stage_gate_reevaluated",
        "capability_image_created",
        "audit_completed",
        "audit_model_fallback",
        "report_completed",
        "report_model_queue_started",
        "report_model_call_started",
        "report_model_call_progress",
        "report_model_call_completed",
        "report_model_fallback",
        "report_model_failed",
        "run_result_saved",
    }
)


class CreateRunBody(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)
    supplemental_information: str = Field(default="", max_length=8000)
    research_route: str = "auto"
    selected_agent_ids: list[str] = Field(default_factory=list)
    max_rounds: int = Field(default=2, ge=1, le=5)
    execution: dict = Field(default_factory=dict)
    analyst_confirmed: bool = False
    interaction_mode: str = "expert"
    discovery_branch: str = "auto"
    execution_profile_id: str = "winning_swarm_dynamic_v2"
    report_template_mode: str = "project_argument_v1"
    source_query_id: str = Field(default="", max_length=128)
    source_query_version: int | None = Field(default=None, ge=1)


class UpdateRunBody(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)
    supplemental_information: str | None = Field(default=None, max_length=8000)
    research_route: str
    selected_agent_ids: list[str]
    max_rounds: int = Field(ge=1, le=5)
    execution: dict = Field(default_factory=dict)
    analyst_confirmed: bool = False
    interaction_mode: str = "expert"
    discovery_branch: str = "auto"
    execution_profile_id: str = ""
    report_template_mode: str = ""


class DeleteRunsBody(BaseModel):
    run_ids: list[str] = Field(min_length=1, max_length=100)


class UpdateRuntimeCapacityBody(BaseModel):
    capacity: int = Field(ge=1, le=8)


class AgentSelectionPreviewBody(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)
    supplemental_information: str = Field(default="", max_length=8000)
    research_route: str = "auto"
    interaction_mode: str = "expert"
    discovery_branch: str = "auto"


def create_app(
    service: ResearchApplicationService | None = None,
    event_repository: object | None = None,
    *,
    agent_config_path: str | Path | None = None,
    preset_config_path: str | Path | None = None,
    query_library_service: QueryLibraryService | None = None,
) -> FastAPI:
    service = service or build_application_service()
    if event_repository is None:
        event_repository = getattr(service, "repository", None)
    app = FastAPI(title="Equipment Deep Research API", version="0.1.0")

    @app.exception_handler(RunNotFoundError)
    async def run_not_found_handler(
        _request: Request,
        _exc: RunNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "run not found"})

    if query_library_service is None:
        query_library_service = build_query_library_service()
        query_library_service.import_seed_manifest(default_seed_manifest())
    app.include_router(create_query_library_router(query_library_service))
    project_root = Path(os.environ.get("EQUIPMENT_DR_PROJECT_ROOT", Path(__file__).resolve().parents[3]))
    output_root = Path(os.environ.get("EQUIPMENT_DR_OUTPUT_ROOT", project_root / "outputs/runs"))
    agent_path = Path(agent_config_path or project_root / "configs/equipment_deep_research/agents.yaml")
    preset_path = Path(preset_config_path or project_root / "configs/equipment_deep_research/presets.yaml")
    catalog_payload = _catalog_payload(agent_path, preset_path)
    agent_registry = AgentRegistry.load(agent_path)
    interaction_agents = _interaction_agents(agent_path)

    def benchmark_research_runs() -> list[dict]:
        rows: list[dict] = []
        for view in service.list_runs():
            if view.status != "completed":
                continue
            run_dir = _resolve_run_root(output_root, view.run_id, view.result)
            if run_dir is None:
                continue
            report_path = _preferred_report_path(run_dir.resolve())
            if report_path is None:
                continue
            rows.append(
                {
                    "run_id": view.run_id,
                    "topic": view.topic,
                    "research_route": view.research_route,
                    "discovery_branch": view.discovery_branch,
                    "execution_profile_id": getattr(view, "execution_profile_id", "") or "legacy_v1",
                    "updated_at": view.updated_at,
                    "report_available": True,
                }
            )
        return rows

    def benchmark_research_report(run_id: str) -> dict:
        view = service.get_run(run_id)
        if view.status != "completed":
            raise ValueError("研究任务尚未完成")
        run_dir = _resolve_run_root(output_root, run_id, view.result)
        if run_dir is None:
            raise FileNotFoundError("研究任务输出目录不存在")
        report_path = _preferred_report_path(run_dir)
        if report_path is None:
            raise FileNotFoundError("研究报告不存在")
        citations: list[str] = []
        sources: list[str] = []
        evidence_context: list[dict] = []
        domain_path = run_dir / "domain.jsonl"
        if domain_path.is_file():
            for row in _jsonl_path(domain_path):
                if row.get("type") != "EvidenceCard":
                    continue
                payload = row.get("payload", {})
                url = str(payload.get("source_url", "")).strip()
                if url and url not in citations:
                    citations.append(url)
                title = str(payload.get("source_title", "")).strip()
                if title and title not in sources:
                    sources.append(title)
                evidence_context.append(
                    {
                        "evidence_id": str(payload.get("evidence_id", "")),
                        "source_title": title,
                        "source_url": url,
                        "source_tier": str(payload.get("source_tier", "")),
                        "quality_assessment": str(
                            payload.get("quality_assessment", "")
                        ),
                        "claim": str(
                            payload.get("claim")
                            or payload.get("evidence_summary")
                            or ""
                        ),
                    }
                )
        summary: dict = {}
        summary_path = run_dir / "round_summary.json"
        if summary_path.is_file():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return {
            "run_id": view.run_id,
            "topic": view.topic,
            "answer": report_path.read_text(encoding="utf-8"),
            "citations": citations,
            "sources": sources,
            "evidence_context": evidence_context,
            "duration_seconds": float(
                summary.get("performance_summary", {}).get("wall_time_seconds", 0.0)
                or 0.0
            ),
            "usage": summary.get("usage", {}),
            "model_snapshot": {
                **dict(summary.get("provider", {})),
                "execution_profile_id": getattr(view, "execution_profile_id", "")
                or "legacy_v1",
            },
            "artifact_refs": [
                f"/api/v1/runs/{run_id}/report",
                f"/api/v1/runs/{run_id}/summary",
            ],
        }
    try:
        from evals.web_api import create_benchmark_router

        app.include_router(
            create_benchmark_router(
                project_root,
                list_research_runs=benchmark_research_runs,
                load_research_report=benchmark_research_report,
            )
        )
    except ImportError:
        # Production research APIs remain available when the optional sidecar
        # benchmark package is not included in a deployment image.
        pass
    if os.environ.get("EQUIPMENT_DR_ENABLE_ABLATION", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }:
        try:
            from evals.ablation import create_ablation_router

            app.include_router(
                create_ablation_router(
                    project_root,
                    list_research_runs=benchmark_research_runs,
                    load_research_report=benchmark_research_report,
                )
            )
        except ImportError:
            # The extension is intentionally removable; core APIs stay intact.
            pass

    def permanently_remove(run_id: str) -> None:
        current = service.get_run(run_id)
        active_worker = any(
            worker.get("online") and worker.get("current_run_id") == run_id
            for worker in service.runtime_health().get("workers", [])
        )
        if current.status not in PERMANENTLY_DELETABLE_STATUSES and active_worker:
            raise InvalidRunTransition(
                f"{current.status} cannot be permanently deleted while an online worker is processing it"
            )
        _delete_run_output(output_root, run_id)
        service.delete_run(
            run_id,
            allow_active=current.status not in PERMANENTLY_DELETABLE_STATUSES,
        )
        _verify_run_deleted(service, output_root, run_id)

    def interaction_rows(run_id: str, view: object) -> list[dict]:
        rows: list[dict] = []
        rows_by_key: dict[str, dict] = {}

        def append_row(row: dict, *, runtime_sequence: int = 0) -> None:
            event_id = str(row.get("event_id", "")).strip()
            key = event_id or "|".join(
                str(row.get(field, ""))
                for field in ("event_type", "actor", "created_at", "summary")
            )
            existing = rows_by_key.get(key)
            if existing is not None:
                # File-backed trace rows are loaded first, while the runtime
                # repository carries the authoritative monotonic sequence.
                # Preserve the richer row but attach its runtime order when
                # the duplicate repository event is encountered.
                if runtime_sequence and not existing.get("_runtime_sequence"):
                    existing["_runtime_sequence"] = runtime_sequence
                return
            row["_runtime_sequence"] = runtime_sequence
            rows_by_key[key] = row
            rows.append(row)

        result = getattr(view, "result", {})
        result = result if isinstance(result, dict) else {}
        root = _resolve_run_root(output_root, run_id, result)
        if root is not None:
            trace_path = root / "trace.jsonl"
            if trace_path.is_file():
                for row in _jsonl_path(trace_path):
                    if row.get("type") != "TraceEvent":
                        continue
                    append_row(_public_trace_interaction(row.get("payload", {})))
            sessions_dir = root / "agent_sessions"
            if sessions_dir.is_dir() and not sessions_dir.is_symlink():
                for path in sorted(sessions_dir.glob("*.jsonl")):
                    if path.is_file() and not path.is_symlink():
                        for event in _jsonl_path(path):
                            public = _public_session_interaction(event)
                            if public is not None:
                                append_row(public)
        if event_repository is not None:
            for runtime_event in event_repository.events_after(run_id, 0):
                payload = runtime_event.get("payload", {})
                source = payload.get("source") if isinstance(payload, dict) else None
                event = payload.get("event", {}) if isinstance(payload, dict) else {}
                public = (
                    _public_trace_interaction(event)
                    if source == "trace"
                    else _public_session_interaction(event)
                    if source == "session_projection"
                    else None
                )
                if public is not None:
                    append_row(public, runtime_sequence=int(runtime_event["sequence"]))
                    continue
                # Runtime terminal events are not represented by TraceEvent files.
                # Keep them in the replay so a failed run cannot appear as merely stalled.
                if runtime_event.get("event_type") in {"run_failed", "run_recovered"}:
                    details = payload if isinstance(payload, dict) else {}
                    append_row(
                        {
                            "event_id": f"runtime-{runtime_event['sequence']}",
                            "event_type": str(runtime_event["event_type"]),
                            "actor": "orchestrator",
                            "title": "任务失败" if runtime_event["event_type"] == "run_failed" else "任务恢复",
                            "summary": str(details.get("error") or details.get("reason") or runtime_event["event_type"]),
                            "created_at": str(getattr(view, "updated_at", "")),
                            "input_refs": [],
                            "output_refs": [],
                            "details": details,
                        },
                        runtime_sequence=int(runtime_event["sequence"]),
                    )
        if event_repository is not None:
            # Repository-backed events are the live, authoritative timeline.
            # File-only session details remain available, but cannot push an
            # older terminal event behind a newer recovery/progress event.
            rows.sort(
                key=lambda item: (
                    0 if not item.get("_runtime_sequence", 0) else 1,
                    item.get("_runtime_sequence", 0),
                    item.get("created_at", ""),
                    item.get("event_id", ""),
                )
            )
        else:
            rows.sort(
                key=lambda item: (
                    item.get("created_at", ""),
                    item.get("event_id", ""),
                )
            )
        for row in rows:
            row.pop("_runtime_sequence", None)
        for sequence, row in enumerate(rows, start=1):
            row.setdefault("sequence", sequence)
        return rows

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/runtime-health")
    def runtime_health(x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        return service.runtime_health()

    @app.put("/api/v1/runtime-capacity")
    def update_runtime_capacity(
        body: UpdateRuntimeCapacityBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        config = write_worker_capacity(body.capacity, updated_by=x_role)
        return {
            "desired_capacity": config["desired_capacity"],
            "runtime": service.runtime_health(),
        }

    @app.get("/api/v1/runs")
    def list_runs(x_role: str = Header(default="analyst", alias="X-Role")) -> list[dict]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        views = service.list_runs()
        actual_by_run: dict[str, list[str]] = {}
        batch_loader = getattr(
            event_repository,
            "actual_baseline_agent_ids_by_run",
            None,
        )
        if callable(batch_loader):
            actual_by_run = batch_loader([item.run_id for item in views])
        elif event_repository is not None:
            actual_by_run = {
                item.run_id: _actual_baseline_agent_ids(
                    event_repository.events_after(item.run_id, 0)
                )
                for item in views
            }
        return [
            {
                **_public_run_view(item, output_root),
                "actual_agent_ids": actual_by_run.get(item.run_id, []),
                "actual_agent_count": len(actual_by_run.get(item.run_id, [])),
            }
            for item in views
        ]

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        try:
            return _public_run_view(service.get_run(run_id), output_root)
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/api/v1/catalog")
    def catalog() -> dict:
        return catalog_payload

    @app.post("/api/v1/agent-selection-preview")
    def agent_selection_preview(body: AgentSelectionPreviewBody) -> dict:
        problem = ResearchProblem(
            topic=body.topic.strip(),
            supplemental_information=body.supplemental_information.strip(),
            research_route=body.research_route,
            interaction_mode=body.interaction_mode,
            discovery_branch=body.discovery_branch,
        )
        available = {
            agent.agent_id: agent.capability_tags
            for agent in agent_registry.enabled_baseline_agents()
        }
        blueprint = build_discovery_blueprint(
            problem,
            available_agent_capabilities=available,
        )
        names = {
            agent.agent_id: agent.display_name
            for agent in agent_registry.enabled_baseline_agents()
        }
        active_plan = [
            {**item, "display_name": names.get(item["agent_id"], item["agent_id"])}
            for item in blueprint["baseline_agent_plan"]
            if item["mode"] in {"required", "reference"}
        ]
        return {
            "primary_branch": blueprint["primary_branch"],
            "branch_name": blueprint["branch_name"],
            "runtime_route": blueprint["runtime_route"],
            "selected_agent_ids": [item["agent_id"] for item in active_plan],
            "plan": active_plan,
            "callback_agent_ids": blueprint["callback_agent_ids"],
            "semantic_signals": blueprint["semantic_agent_signals"],
            "structured_query_brief": blueprint["structured_query_brief"],
            "policy": "Query主导军事作战发散 + A–H分支 + 能力覆盖；optimized_v2首轮3–4个独立Agent并行",
        }

    @app.post("/api/v1/runs", status_code=201)
    def create_run(body: CreateRunBody, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        valid_routes = {item["id"] for item in catalog_payload["routes"]} | {"auto"}
        valid_agents = {item["agent_id"] for item in catalog_payload["agents"]}
        unknown_agents = sorted(set(body.selected_agent_ids) - valid_agents)
        if body.research_route not in valid_routes:
            raise HTTPException(status_code=422, detail="unknown research route")
        if body.interaction_mode not in {"expert", "autonomous"}:
            raise HTTPException(status_code=422, detail="unknown interaction mode")
        if body.discovery_branch not in {"auto", "A", "B", "C", "D", "E", "F", "G", "H"}:
            raise HTTPException(status_code=422, detail="unknown discovery branch")
        if body.execution_profile_id not in {
            "",
            "legacy_v1",
            "optimized_v2",
            "swarm_quality_v1",
            "winning_swarm_dynamic_v2",
        }:
            raise HTTPException(status_code=422, detail="unknown execution profile")
        if body.report_template_mode not in {
            "three_layer_nine_item",
            "project_argument_v1",
        }:
            raise HTTPException(status_code=422, detail="unknown report template mode")
        if unknown_agents:
            raise HTTPException(status_code=422, detail=f"unknown agent ids: {unknown_agents}")
        try:
            execution = _validated_execution(body.execution, catalog_payload["provider"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if body.source_query_id:
            try:
                source_query = query_library_service.get_query(
                    body.source_query_id, include_revisions=False
                )
            except QueryLibraryError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if source_query["status"] != "published":
                raise HTTPException(
                    status_code=409,
                    detail="source Query must be published before creating a research task",
                )
            if (
                body.source_query_version is not None
                and source_query["version"] != body.source_query_version
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "source Query version changed; review the latest revision before "
                        "creating a research task"
                    ),
                )
            execution["query_library"] = {
                "query_id": source_query["query_id"],
                "version": source_query["version"],
                "source_type": source_query["source_type"],
            }
        return service.create_run(
            CreateRunCommand(
                topic=body.topic.strip(),
                research_route=body.research_route,
                selected_agent_ids=body.selected_agent_ids,
                max_rounds=body.max_rounds,
                created_by="api-user",
                execution=execution,
                analyst_confirmed=body.analyst_confirmed,
                interaction_mode=body.interaction_mode,
                discovery_branch=body.discovery_branch,
                execution_profile_id=body.execution_profile_id,
                report_template_mode=body.report_template_mode,
                supplemental_information=body.supplemental_information.strip(),
            )
        ).__dict__

    @app.post("/api/v1/runs/{run_id}/start")
    def start_run(run_id: str, idempotency_key: str = Header(alias="Idempotency-Key"), x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        try:
            run = service.get_run(run_id)
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        missing_credentials = _missing_execution_credentials(run.execution)
        if missing_credentials:
            raise HTTPException(
                status_code=422,
                detail=(
                    "missing configured provider credentials: "
                    + ", ".join(missing_credentials)
                ),
            )
        try:
            return service.start_run(run_id, actor="api-user", idempotency_key=idempotency_key).__dict__
        except InvalidRunTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/resume")
    def resume_run(run_id: str, idempotency_key: str = Header(alias="Idempotency-Key"), x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        """Resume a paused run or retry a failed run from its checkpoint."""

        _require_role(x_role, {"analyst", "admin"})
        try:
            run = service.get_run(run_id)
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        resume_execution = dict(run.execution)
        if resume_execution.get("mode") == "real":
            try:
                resume_execution = _validated_execution(
                    {
                        "mode": "real",
                        "provider": resume_execution.get("provider", "codex"),
                    },
                    catalog_payload["provider"],
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        missing_credentials = _missing_execution_credentials(resume_execution)
        if missing_credentials:
            raise HTTPException(
                status_code=422,
                detail=(
                    "missing configured provider credentials: "
                    + ", ".join(missing_credentials)
                ),
            )
        try:
            return service.resume_run(
                run_id,
                actor="api-user",
                idempotency_key=idempotency_key,
                execution=resume_execution,
            ).__dict__
        except InvalidRunTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.patch("/api/v1/runs/{run_id}")
    def update_run(
        run_id: str,
        body: UpdateRunBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        valid_routes = {item["id"] for item in catalog_payload["routes"]} | {"auto"}
        valid_agents = {item["agent_id"] for item in catalog_payload["agents"]}
        unknown_agents = sorted(set(body.selected_agent_ids) - valid_agents)
        if body.research_route not in valid_routes:
            raise HTTPException(status_code=422, detail="unknown research route")
        if body.interaction_mode not in {"expert", "autonomous"}:
            raise HTTPException(status_code=422, detail="unknown interaction mode")
        if body.discovery_branch not in {"auto", "A", "B", "C", "D", "E", "F", "G", "H"}:
            raise HTTPException(status_code=422, detail="unknown discovery branch")
        if body.execution_profile_id not in {
            "",
            "legacy_v1",
            "optimized_v2",
            "swarm_quality_v1",
            "winning_swarm_dynamic_v2",
        }:
            raise HTTPException(status_code=422, detail="unknown execution profile")
        if body.report_template_mode not in {
            "",
            "three_layer_nine_item",
            "project_argument_v1",
        }:
            raise HTTPException(status_code=422, detail="unknown report template mode")
        if unknown_agents:
            raise HTTPException(status_code=422, detail=f"unknown agent ids: {unknown_agents}")
        try:
            execution = _validated_execution(body.execution, catalog_payload["provider"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            current = service.get_run(run_id)
            query_reference = current.execution.get("query_library")
            if isinstance(query_reference, dict):
                execution["query_library"] = dict(query_reference)
            return service.update_run(
                run_id,
                UpdateRunCommand(
                    topic=body.topic,
                    research_route=body.research_route,
                    selected_agent_ids=body.selected_agent_ids,
                    max_rounds=body.max_rounds,
                    execution=execution,
                    analyst_confirmed=body.analyst_confirmed,
                    interaction_mode=body.interaction_mode,
                    discovery_branch=body.discovery_branch,
                    execution_profile_id=body.execution_profile_id,
                    report_template_mode=body.report_template_mode,
                    supplemental_information=(
                        None
                        if body.supplemental_information is None
                        else body.supplemental_information.strip()
                    ),
                ),
                actor="api-user",
            ).__dict__
        except InvalidRunTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.delete("/api/v1/runs/{run_id}")
    def archive_run(
        run_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        try:
            return service.archive_run(run_id, actor="api-user").__dict__
        except (KeyError, NoResultFound, InvalidRunTransition) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/api/v1/runs/{run_id}/permanent")
    def permanently_delete_run(
        run_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        try:
            permanently_remove(run_id)
            return {"run_id": run_id, "deleted": True}
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except InvalidRunTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/v1/runs/permanent-delete")
    def permanently_delete_runs(
        body: DeleteRunsBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        deleted = []
        rejected = []
        for run_id in dict.fromkeys(body.run_ids):
            try:
                permanently_remove(run_id)
                deleted.append(run_id)
            except (KeyError, NoResultFound):
                rejected.append({"run_id": run_id, "reason": "run not found"})
            except InvalidRunTransition as exc:
                rejected.append({"run_id": run_id, "reason": str(exc)})
            except RuntimeError as exc:
                rejected.append({"run_id": run_id, "reason": str(exc)})
        return {"deleted": deleted, "rejected": rejected}

    @app.get("/api/v1/runs/{run_id}/history")
    def get_run_history(
        run_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> list[dict]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        try:
            service.get_run(run_id)
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        rows = [] if event_repository is None else event_repository.events_after(run_id, 0)
        return [
            {
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "payload": sanitize_runtime_payload(row["payload"]),
            }
            for row in rows
        ]

    @app.get("/api/v1/runs/{run_id}/events")
    async def replay_events(run_id: str, last_event_id: int = Header(default=0, alias="Last-Event-ID"), x_role: str = Header(default="analyst", alias="X-Role")) -> StreamingResponse:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        async def stream():
            cursor = last_event_id
            idle_cycles = 0
            while True:
                rows = [] if event_repository is None else event_repository.events_after(run_id, cursor)
                for row in rows:
                    cursor = int(row["sequence"])
                    yield f"id: {cursor}\nevent: {row['event_type']}\ndata: {json.dumps(row['payload'], ensure_ascii=False)}\n\n"
                idle_cycles = 0 if rows else idle_cycles + 1
                try:
                    status = service.get_run(run_id).status
                except (KeyError, NoResultFound):
                    break
                if status in {"completed", "failed", "cancelled"} and not rows:
                    break
                if idle_cycles >= 20:
                    idle_cycles = 0
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)
        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v1/runs/{run_id}/summary")
    def get_summary(run_id: str, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = service.get_run(run_id)
        if _is_historical_snapshot(view):
            return {
                "run_id": run_id,
                "topic": view.topic,
                "historical_snapshot": True,
                "message": "原始任务产物未随恢复快照保存，未伪造摘要。",
            }
        return _read_json(service, output_root, run_id, "round_summary.json")

    @app.get("/api/v1/runs/{run_id}/capabilities")
    def get_capabilities(run_id: str, x_role: str = Header(default="analyst", alias="X-Role")) -> list[dict]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = service.get_run(run_id)
        if _is_historical_snapshot(view):
            return []
        # While a run is active, expose the latest frozen S6 portfolio. Once
        # delivery completes, capability_images.json is authoritative because
        # it contains the accepted parallel S6 prose and any identity restored
        # from the pre-S6 hypothesis ledger. Returning the earlier portfolio
        # event after completion would surface stale titles and omit portraits.
        workflow = _interaction_workflow_summary(interaction_rows(run_id, view), view)
        portfolio = workflow.get("swarm_cluster", {}).get(
            "final_equipment_portfolio", []
        )
        provisional_rows = _provisional_s6_capability_rows(portfolio)
        if view.status != "completed" and provisional_rows:
            return [_capability_api_view(row) for row in provisional_rows]
        try:
            payload = _read_json(service, output_root, run_id, "capability_images.json")
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            if provisional_rows:
                return [_capability_api_view(row) for row in provisional_rows]
            raise
        else:
            rows = payload if isinstance(payload, list) else payload.get("capability_images", [])
        return [_capability_api_view(row) for row in rows if isinstance(row, dict)]

    @app.get("/api/v1/runs/{run_id}/domain/{object_type}")
    def get_domain_objects(run_id: str, object_type: str, x_role: str = Header(default="analyst", alias="X-Role")) -> list[dict]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        if _is_historical_snapshot(service.get_run(run_id)):
            return []
        allowed = {
            "EvidenceCard",
            "BaselineFindingPacket",
            "WinningMechanismInput",
            "WinningKnowledgeProjection",
            "WinningReasoningNode",
            "WinningMechanismStageOutput",
            "RecallRequest",
            "AuditResult",
        }
        if object_type not in allowed:
            raise HTTPException(status_code=404, detail="domain object type not exposed")
        return [row["payload"] for row in _read_jsonl(service, output_root, run_id, "domain.jsonl") if row.get("type") == object_type]

    @app.get("/api/v1/runs/{run_id}/winning-mechanism")
    def get_winning_mechanism(run_id: str, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = service.get_run(run_id)
        if _is_historical_snapshot(view):
            return {
                "inputs": [],
                "resources": [],
                "reasoning_nodes": [],
                "stages": [],
                "recalls": [],
                "workflow": _interaction_workflow_summary(interaction_rows(run_id, view), view),
                "historical_snapshot": True,
                "message": "原始制胜机理产物未随恢复快照保存。",
            }
        grouped = {
            "inputs": [],
            "resources": [],
            "reasoning_nodes": [],
            "stages": [],
            "recalls": [],
        }
        mapping = {
            "WinningMechanismInput": "inputs",
            "WinningKnowledgeProjection": "resources",
            "WinningReasoningNode": "reasoning_nodes",
            "WinningMechanismStageOutput": "stages",
            "RecallRequest": "recalls",
        }
        for row in _read_jsonl(service, output_root, run_id, "domain.jsonl"):
            target = mapping.get(row.get("type"))
            if target:
                grouped[target].append(row.get("payload", {}))
        grouped["reasoning_nodes"].sort(key=lambda item: (item.get("step", 0), item.get("created_at", "")))
        grouped["workflow"] = _interaction_workflow_summary(
            interaction_rows(run_id, view),
            view,
        )
        try:
            summary = _read_json(service, output_root, run_id, "round_summary.json")
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            summary = {}
        grouped["swarm"] = (
            dict(summary.get("winning_swarm", {}))
            if isinstance(summary, dict)
            and isinstance(summary.get("winning_swarm", {}), dict)
            else {}
        )
        return grouped

    @app.get("/api/v1/runs/{run_id}/trace")
    def get_trace(run_id: str, x_role: str = Header(default="auditor", alias="X-Role")) -> list[dict]:
        _require_role(x_role, {"auditor", "admin"})
        if _is_historical_snapshot(service.get_run(run_id)):
            return []
        return _read_jsonl(service, output_root, run_id, "trace.jsonl")

    @app.get("/api/v1/runs/{run_id}/interactions")
    def get_interactions(
        run_id: str,
        compact: bool = False,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = service.get_run(run_id)
        rows = interaction_rows(run_id, view)
        visible_rows = _compact_interactions(rows) if compact else rows
        workflow = _interaction_workflow_summary(rows, view)
        return {
            "run_id": run_id,
            "agents": _interaction_agents_with_runtime(
                interaction_agents,
                rows,
            ),
            "events": visible_rows,
            "workflow": workflow,
            "counts": {
                "events": len(rows),
                "visible_events": len(visible_rows),
                "active_agents": len(workflow["active_agent_ids"]),
                "tool_calls": sum(item["event_type"] == "tool_call" for item in rows),
                "tool_results": sum(item["event_type"] == "tool_result" for item in rows),
                "savepoints": sum(item["event_type"] == "savepoint" for item in rows),
            },
        }

    @app.get("/api/v1/runs/{run_id}/report", response_class=PlainTextResponse)
    def get_report(run_id: str, x_role: str = Header(default="reviewer", alias="X-Role")) -> str:
        _require_role(x_role, {"reviewer", "auditor", "admin"})
        view = service.get_run(run_id)
        if _is_historical_snapshot(view):
            return _historical_snapshot_report(view)
        report_path = _preferred_report_path(_run_root(service, output_root, run_id))
        if report_path is None:
            raise HTTPException(status_code=404, detail="run output not found")
        return report_path.read_text(encoding="utf-8")

    @app.get("/api/v1/runs/{run_id}/deliverables")
    def get_deliverables(
        run_id: str,
        x_role: str = Header(default="reviewer", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"reviewer", "auditor", "admin"})
        branch_deliverables = _read_json(service, output_root, run_id, "branch_deliverables.json")
        payload = {"branch_deliverables": branch_deliverables}
        if str(branch_deliverables.get("branch", "")) == "B":
            payload.update(
                {
                    "demand_cards": _read_json(service, output_root, run_id, "demand_cards.json"),
                    "capability_panorama": _read_json(
                        service, output_root, run_id, "capability_panorama.json"
                    ),
                    "reasoning_traceability": _read_json(
                        service, output_root, run_id, "reasoning_traceability.json"
                    ),
                }
            )
        return payload

    @app.get("/api/v1/runs/{run_id}/manifest")
    def get_manifest(run_id: str, x_role: str = Header(default="auditor", alias="X-Role")) -> dict:
        _require_role(x_role, {"auditor", "admin"})
        return _read_json(service, output_root, run_id, "delivery-manifest.json")

    @app.get("/api/v1/runs/{run_id}/artifacts/{artifact_name}")
    def get_artifact(run_id: str, artifact_name: str, x_role: str = Header(default="reviewer", alias="X-Role")) -> FileResponse:
        _require_role(x_role, {"reviewer", "auditor", "admin"})
        if Path(artifact_name).name != artifact_name:
            raise HTTPException(status_code=400, detail="invalid artifact name")
        path = _run_file(service, output_root, run_id, f"artifacts/{artifact_name}")
        return FileResponse(path)
    return app


def _compact_interactions(rows: list[dict], limit: int = 80) -> list[dict]:
    important = [
        row for row in rows
        if str(row.get("event_type", "")) in _KEY_INTERACTION_EVENT_TYPES
    ]
    selected = important or rows[-min(limit, len(rows)):]
    if len(selected) <= limit:
        return selected
    head_count = min(12, limit // 4)
    return [*selected[:head_count], *selected[-(limit - head_count):]]


def _interaction_workflow_summary(rows: list[dict], view: object) -> dict:
    started = next(
        (row for row in rows if row.get("event_type") == "run_started"),
        {},
    )
    started_details = (
        dict(started.get("details", {}))
        if isinstance(started.get("details"), dict)
        else {}
    )
    blueprint = (
        dict(started_details.get("discovery_blueprint", {}))
        if isinstance(started_details.get("discovery_blueprint"), dict)
        else {}
    )
    meta_events = [
        row for row in rows
        if row.get("event_type") == "discovery_meta_loop_evaluated"
    ]
    meta_details = (
        dict(meta_events[-1].get("details", {}))
        if meta_events and isinstance(meta_events[-1].get("details"), dict)
        else {}
    )
    execution = getattr(view, "execution", {})
    execution = dict(execution) if isinstance(execution, dict) else {}
    l4_step_overrides: list[dict] = []
    for meta_event in meta_events:
        details = meta_event.get("details", {})
        if not isinstance(details, dict):
            continue
        raw_overrides = details.get("step_mode_overrides", [])
        if not isinstance(raw_overrides, list):
            continue
        l4_step_overrides.extend(
            dict(item) for item in raw_overrides if isinstance(item, dict)
        )
    primary_branch = str(
        meta_details.get("primary_branch")
        or blueprint.get("primary_branch")
        or getattr(view, "discovery_branch", "")
    )
    if primary_branch not in BRANCH_BLUEPRINTS:
        primary_branch = {
            "new_winning_mechanism": "A",
            "traditional_gap": "B",
            "war_case_learning": "C",
        }.get(str(getattr(view, "research_route", "")), "")
    mode_branch = primary_branch or "B"
    adaptive_modes = blueprint.get("adaptive_winning_step_modes", {})
    pre_l4_modes = winning_step_modes(
        mode_branch,
        research_route=str(getattr(view, "research_route", "")),
        adaptive_modes=(
            adaptive_modes if isinstance(adaptive_modes, dict) else None
        ),
    )
    resolved_modes = winning_step_modes(
        mode_branch,
        research_route=str(getattr(view, "research_route", "")),
        adaptive_modes=(
            adaptive_modes if isinstance(adaptive_modes, dict) else None
        ),
        l4_overrides=l4_step_overrides,
    )
    execution_profile_id = str(
        getattr(view, "execution_profile_id", "") or "legacy_v1"
    )
    # A terminal completed/approved run is authoritative.  Older or duplicate
    # workers may append a late ``run_failed``/``report_model_failed`` event
    # after the Reporter has already persisted its report; that stale event
    # must not make the replay banner claim that delivery failed.
    view_result = getattr(view, "result", {})
    view_result = view_result if isinstance(view_result, dict) else {}
    run_has_complete_report = (
        str(getattr(view, "status", "")).lower() == "completed"
        and (
            str(view_result.get("audit_status", "")).lower() in {"approved", "passed"}
            or bool(view_result.get("report_available"))
        )
    )
    is_dynamic_profile = execution_profile_id == "winning_swarm_dynamic_v2"
    latest_steps: dict[int, dict] = {
        int(definition["step"]): {
            "step": int(definition["step"]),
            "agent_id": str(definition["agent_id"]),
            "label": str(definition["label"]),
            "planned_execution_mode": resolved_modes[int(definition["step"])],
            "execution_mode": (
                "dynamic"
                if is_dynamic_profile
                else resolved_modes[int(definition["step"])]
            ),
            "status": "pending" if is_dynamic_profile else (
                "skipped"
                if resolved_modes[int(definition["step"])] == "skip"
                else "pending"
            ),
            "decision_finalized": False,
            "middle_cycle": 0,
            "result_summary": "",
            "backtrack_count": 0,
        }
        for definition in WINNING_STEP_DEFINITIONS
    }
    dynamic_agents_by_id: dict[str, dict] = {}
    swarm_member_ids: set[str] = set()
    swarm_event_seen = False
    swarm_plan_details: dict = {}
    mission_graph_projection: dict = {}
    role_contracts_by_id: dict[str, dict] = {}
    candidate_lineage_by_id: dict[str, dict] = {}
    merge_receipts_by_id: dict[str, dict] = {}
    ledger_projection: dict = {}
    portfolio_projection: dict = {}

    def safe_string_list(value: object, *, limit: int = 24) -> list[str]:
        if not isinstance(value, (list, tuple, set)):
            return []
        return [str(item)[:300] for item in value if str(item).strip()][:limit]

    def update_candidate(hypothesis_id: str, values: dict) -> dict:
        current = candidate_lineage_by_id.setdefault(
            hypothesis_id,
            {
                "hypothesis_id": hypothesis_id,
                "status": "created",
                "source_member_ids": [],
                "merge_targets": [],
                "receipt_ids": [],
            },
        )
        for key, value in values.items():
            if value in (None, "", [], {}):
                continue
            current[key] = value
        return current

    def append_candidate_value(
        hypothesis_id: str,
        key: str,
        value: object,
        *,
        limit: int = 24,
    ) -> None:
        if not hypothesis_id or value in (None, ""):
            return
        current = update_candidate(hypothesis_id, {})
        values = current.setdefault(key, [])
        if not isinstance(values, list):
            values = []
            current[key] = values
        text_value = str(value)
        if text_value not in values and len(values) < limit:
            values.append(text_value)

    def update_dynamic_agent(
        dynamic_agent_id: str,
        values: dict,
    ) -> dict:
        current = dynamic_agents_by_id.setdefault(
            dynamic_agent_id,
            {
                "agent_id": dynamic_agent_id,
                "agent_instance_id": dynamic_agent_id,
                "display_name": "动态专用 Agent",
                "status": "planned",
            },
        )
        for key, value in values.items():
            if value in (None, "", [], {}):
                continue
            current[key] = value
        return current

    for row in rows:
        event_type = str(row.get("event_type", ""))
        details = row.get("details", {})
        details = details if isinstance(details, dict) else {}
        if event_type == "swarm_planned":
            swarm_event_seen = True
            swarm_plan_details = dict(details)
            continue
        if event_type == "winning_mission_graph_planned":
            swarm_event_seen = True
            graph = details.get("graph", {})
            graph = graph if isinstance(graph, dict) else {}
            graph_id = str(details.get("graph_id") or graph.get("graph_id") or "")
            execution_profile_id = str(graph.get("execution_profile_id", ""))
            mission_graph_projection = {
                "graph_id": graph_id,
                "execution_profile_id": execution_profile_id,
                "status": str(graph.get("status", "planned")),
                "minimum_instances": details.get(
                    "minimum_instances", graph.get("minimum_instances")
                ),
                "maximum_instances": details.get(
                    "maximum_instances", graph.get("maximum_instances")
                ),
                "maximum_concurrency": details.get(
                    "maximum_concurrency", graph.get("maximum_concurrency")
                ),
                "merge_strategy": str(graph.get("merge_strategy", "")),
                "waves": [
                    safe_string_list(item, limit=16)
                    for item in graph.get("waves", [])
                    if isinstance(item, list)
                ][:6],
            }
            swarm_plan_details = {
                **swarm_plan_details,
                "policy_id": execution_profile_id or "winning_swarm_dynamic_v2",
            }
            raw_contracts = graph.get("role_contracts", [])
            if isinstance(raw_contracts, list):
                for raw_contract in raw_contracts:
                    if not isinstance(raw_contract, dict):
                        continue
                    contract_id = str(raw_contract.get("role_contract_id", ""))
                    if not contract_id:
                        continue
                    role_contracts_by_id[contract_id] = {
                        "role_contract_id": contract_id,
                        "archetype": str(raw_contract.get("archetype", "")),
                        "display_name": str(raw_contract.get("display_name", "")),
                        "role_purpose": str(raw_contract.get("purpose", ""))[:600],
                        "mission_node": str(raw_contract.get("mission_node", "")),
                        "merge_targets": safe_string_list(
                            raw_contract.get("merge_targets", []), limit=6
                        ),
                        "trigger_residuals": safe_string_list(
                            raw_contract.get("trigger_residuals", []), limit=8
                        ),
                        "skill_ids": safe_string_list(
                            raw_contract.get("skill_ids", []), limit=8
                        ),
                        "allow_child_spawn": False,
                        "authority_scope": str(
                            raw_contract.get("authority_scope", "bounded_analysis_only")
                        ),
                        "role_contract_version": str(
                            raw_contract.get("schema_version", "2.0")
                        ),
                    }
            raw_instances = graph.get("agent_instances", [])
            if isinstance(raw_instances, list):
                for raw_instance in raw_instances:
                    if not isinstance(raw_instance, dict):
                        continue
                    instance_id = str(
                        raw_instance.get("instance_id")
                        or raw_instance.get("agent_instance_id")
                        or ""
                    ).strip()
                    if not instance_id:
                        continue
                    swarm_member_ids.add(instance_id)
                    contract = role_contracts_by_id.get(
                        str(raw_instance.get("role_contract_id", "")), {}
                    )
                    mission_node = str(
                        raw_instance.get("mission_node")
                        or raw_instance.get("merge_target")
                        or contract.get("mission_node", "")
                    )
                    update_dynamic_agent(
                        instance_id,
                        {
                            "task_id": instance_id,
                            "agent_instance_id": instance_id,
                            "display_name": str(
                                raw_instance.get("display_name")
                                or contract.get("display_name")
                                or "动态专用 Agent"
                            ),
                            "archetype": str(
                                raw_instance.get("archetype")
                                or contract.get("archetype", "")
                            ),
                            "role_purpose": str(contract.get("role_purpose", "")),
                            "role_contract_id": str(
                                raw_instance.get("role_contract_id", "")
                            ),
                            "role_contract_version": str(
                                contract.get("role_contract_version", "2.0")
                            ),
                            "mission_node": mission_node,
                            "merge_target": str(
                                raw_instance.get("merge_target") or mission_node
                            ),
                            "wave": raw_instance.get("wave", 0),
                            "hypothesis_id": str(
                                raw_instance.get("hypothesis_id", "")
                            ),
                            "depends_on": safe_string_list(
                                raw_instance.get("depends_on", []), limit=16
                            ),
                            "trigger_residuals": safe_string_list(
                                raw_instance.get(
                                    "trigger_residuals",
                                    contract.get("trigger_residuals", []),
                                ),
                                limit=8,
                            ),
                            "skill_ids": safe_string_list(
                                contract.get("skill_ids", []), limit=8
                            ),
                            "execution_backend": str(
                                raw_instance.get(
                                    "execution_backend", "independent_codex_cli"
                                )
                            ),
                            "context_isolation": str(
                                raw_instance.get("context_isolation", "ephemeral")
                            ),
                            "allow_child_spawn": False,
                            "expected_quality_gain": raw_instance.get(
                                "expected_quality_gain"
                            ),
                            "status": "planned",
                            "last_event_type": event_type,
                            "last_sequence": row.get("sequence", 0),
                        },
                    )
            continue
        if event_type == "winning_s3_active_agents_materialized":
            swarm_event_seen = True
            active_ids = {
                str(value).strip()
                for value in details.get("active_instance_ids", [])
                if str(value).strip()
            }
            for instance_id, member in dynamic_agents_by_id.items():
                if (
                    str(member.get("mission_node", "")) == "S3"
                    and not str(member.get("hypothesis_id", ""))
                    and instance_id not in active_ids
                ):
                    swarm_member_ids.discard(instance_id)
                    update_dynamic_agent(
                        instance_id,
                        {
                            "status": "skipped",
                            "inactive_capacity": True,
                            "last_event_type": event_type,
                            "last_sequence": row.get("sequence", 0),
                        },
                    )
            mission_graph_projection["active_s3_instances"] = len(active_ids)
            mission_graph_projection["unused_s3_capacity"] = details.get(
                "unused_capacity_count", 0
            )
            continue
        if event_type == "winning_agent_instance_recruited":
            swarm_event_seen = True
            raw_contract = details.get("role_contract", {})
            raw_contract = raw_contract if isinstance(raw_contract, dict) else {}
            raw_instance = details.get("instance", {})
            raw_instance = raw_instance if isinstance(raw_instance, dict) else {}
            contract_id = str(raw_contract.get("role_contract_id", ""))
            if contract_id:
                role_contracts_by_id[contract_id] = {
                    "role_contract_id": contract_id,
                    "archetype": str(raw_contract.get("archetype", "")),
                    "display_name": str(raw_contract.get("display_name", "")),
                    "role_purpose": str(raw_contract.get("purpose", ""))[:600],
                    "mission_node": str(raw_contract.get("mission_node", "")),
                    "merge_targets": safe_string_list(
                        raw_contract.get("merge_targets", []), limit=6
                    ),
                    "trigger_residuals": safe_string_list(
                        raw_contract.get("trigger_residuals", []), limit=8
                    ),
                    "skill_ids": safe_string_list(
                        raw_contract.get("skill_ids", []), limit=8
                    ),
                    "allow_child_spawn": False,
                    "authority_scope": str(
                        raw_contract.get("authority_scope", "bounded_analysis_only")
                    ),
                    "role_contract_version": str(
                        raw_contract.get("schema_version", "2.0")
                    ),
                }
            instance_id = str(
                raw_instance.get("instance_id")
                or details.get("agent_instance_id")
                or row.get("actor", "")
            ).strip()
            if instance_id:
                swarm_member_ids.add(instance_id)
                contract = role_contracts_by_id.get(contract_id, {})
                update_dynamic_agent(
                    instance_id,
                    {
                        "agent_instance_id": instance_id,
                        "display_name": str(
                            raw_instance.get("display_name")
                            or contract.get("display_name")
                            or "动态专用 Agent"
                        ),
                        "archetype": str(
                            raw_instance.get("archetype")
                            or contract.get("archetype", "")
                        ),
                        "role_purpose": str(contract.get("role_purpose", "")),
                        "role_contract_id": contract_id,
                        "mission_node": str(raw_instance.get("mission_node", "")),
                        "merge_target": str(raw_instance.get("merge_target", "")),
                        "hypothesis_id": str(
                            raw_instance.get("hypothesis_id")
                            or details.get("hypothesis_id", "")
                        ),
                        "depends_on": safe_string_list(
                            raw_instance.get("depends_on", []), limit=16
                        ),
                        "trigger_residuals": safe_string_list(
                            raw_instance.get("trigger_residuals", []), limit=8
                        ),
                        "wave": raw_instance.get("wave", 0),
                        "execution_backend": "independent_codex_cli",
                        "context_isolation": "ephemeral",
                        "allow_child_spawn": False,
                        "recruitment_planned": True,
                        "status": "recruiting",
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    },
                )
            continue
        if event_type == "winning_agent_waiting":
            # Controller-level heartbeat: refresh the already-known members
            # without creating a fake "winning_swarm_controller" Agent card.
            swarm_event_seen = True
            for waiting in details.get("running_instances", []) if isinstance(details.get("running_instances", []), list) else []:
                if not isinstance(waiting, Mapping):
                    continue
                waiting_id = str(waiting.get("agent_instance_id", "")).strip()
                if not waiting_id:
                    continue
                swarm_member_ids.add(waiting_id)
                update_dynamic_agent(
                    waiting_id,
                    {
                        "agent_instance_id": waiting_id,
                        "mission_node": str(waiting.get("mission_node", "")),
                        "archetype": str(waiting.get("archetype", "")),
                        "batch": waiting.get("batch"),
                        "elapsed_seconds": waiting.get("elapsed_seconds"),
                        "status": "running",
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    },
                )
            continue
        if event_type in {
            "winning_agent_instance_ready",
            "winning_agent_session_started",
            "winning_agent_session_completed",
            "winning_agent_instance_failed",
            "winning_agent_instance_cancelled",
        }:
            swarm_event_seen = True
            instance_id = str(
                details.get("agent_instance_id") or row.get("actor", "")
            ).strip()
            if instance_id:
                swarm_member_ids.add(instance_id)
                status = {
                    "winning_agent_instance_ready": "queued",
                    "winning_agent_session_started": "running",
                    "winning_agent_session_completed": "completed",
                    "winning_agent_instance_failed": "failed",
                    "winning_agent_instance_cancelled": "pruned",
                }[event_type]
                safe_fields = {
                    key: details.get(key)
                    for key in (
                        "task_id",
                        "agent_instance_id",
                        "display_name",
                        "archetype",
                        "role_purpose",
                        "trigger_residuals",
                        "wave",
                        "batch",
                        "hypothesis_id",
                        "merge_target",
                        "mission_node",
                        "role_contract_id",
                        "depends_on",
                        "provider_type",
                        "execution_backend",
                        "context_isolation",
                        "provider_isolation_id",
                        "process_isolation",
                        "sandbox_mode",
                        "model",
                        "runtime_profile_id",
                        "role_contract_version",
                        "skill_ids",
                        "allow_child_spawn",
                        "expected_quality_gain",
                        "session_ref",
                        "elapsed_seconds",
                        "running_instances",
                        "note",
                    )
                }
                safe_fields.update(
                    {
                        "status": status,
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    }
                )
                if event_type == "winning_agent_instance_failed":
                    safe_fields["failure_type"] = str(
                        details.get("failure_type", "execution_failed")
                    )
                if event_type == "winning_agent_instance_cancelled":
                    safe_fields["prune_reason"] = str(
                        details.get("reason", "unsatisfied_dependency")
                    )
                update_dynamic_agent(instance_id, safe_fields)
            continue
        if event_type in {
            "winning_quality_judge_recruited",
            "winning_quality_judge_started",
            "winning_quality_judge_completed",
            "winning_quality_judge_failed",
        }:
            swarm_event_seen = True
            instance_id = str(row.get("actor", "")).strip()
            if instance_id:
                swarm_member_ids.add(instance_id)
                status = {
                    "winning_quality_judge_recruited": "recruiting",
                    "winning_quality_judge_started": "running",
                    "winning_quality_judge_completed": "completed",
                    "winning_quality_judge_failed": "failed",
                }[event_type]
                role_contract = details.get("role_contract", {})
                role_contract = (
                    role_contract if isinstance(role_contract, dict) else {}
                )
                update_dynamic_agent(
                    instance_id,
                    {
                        "agent_instance_id": instance_id,
                        "display_name": str(
                            role_contract.get(
                                "display_name", "制胜机理质量专家评判"
                            )
                        ),
                        "archetype": "quality_expert_judge",
                        "mission_node": "convergence",
                        "merge_target": "convergence",
                        "execution_backend": "independent_codex_cli",
                        "context_isolation": "ephemeral_read_only",
                        "allow_child_spawn": False,
                        "candidate_count": details.get("candidate_count"),
                        "assessed_count": details.get("assessed_count"),
                        "session_ref": str(details.get("session_ref", "")),
                        "status": status,
                        "failure_type": str(details.get("failure_type", "")),
                        "error_message": str(details.get("error_message", "")),
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    },
                )
            continue
        if event_type == "winning_quality_judge_assessed":
            swarm_event_seen = True
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            assessment = details.get("assessment", {})
            assessment = assessment if isinstance(assessment, dict) else {}
            if hypothesis_id:
                update_candidate(
                    hypothesis_id,
                    {
                        "expert_assessment_id": str(
                            assessment.get("assessment_id", "")
                        ),
                        "expert_verdict": str(assessment.get("verdict", "")),
                        "expert_passed": assessment.get("passed") is True,
                        "expert_score": assessment.get("weighted_score"),
                        "expert_dimension_scores": dict(
                            assessment.get("dimension_scores", {})
                        )
                        if isinstance(assessment.get("dimension_scores"), dict)
                        else {},
                        "expert_rejection_reasons": safe_string_list(
                            assessment.get("rejection_reasons", []), limit=8
                        ),
                        "status": (
                            "expert_passed"
                            if assessment.get("passed") is True
                            else "expert_rejected"
                        ),
                    },
                )
            continue
        if event_type in {
            "winning_quality_repair_planned",
            "winning_quality_repair_completed",
            "winning_quality_repair_failed",
        }:
            swarm_event_seen = True
            instance_id = str(row.get("actor", "")).strip()
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            if instance_id:
                status = {
                    "winning_quality_repair_planned": "queued",
                    "winning_quality_repair_completed": "completed",
                    "winning_quality_repair_failed": "failed",
                }[event_type]
                update_dynamic_agent(
                    instance_id,
                    {
                        "agent_instance_id": instance_id,
                        "hypothesis_id": hypothesis_id,
                        "archetype": str(
                            details.get("archetype", "expert_residual_repair")
                        ),
                        "execution_backend": "independent_codex_cli",
                        "context_isolation": "ephemeral",
                        "allow_child_spawn": False,
                        "expert_assessment_id": str(
                            details.get("expert_assessment_id", "")
                        ),
                        "repair_residuals": safe_string_list(
                            details.get("residuals", []), limit=8
                        ),
                        "status": status,
                        "error_message": str(details.get("error_message", "")),
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    },
                )
            if hypothesis_id:
                update_candidate(
                    hypothesis_id,
                    {
                        "status": (
                            "expert_repair_completed"
                            if event_type == "winning_quality_repair_completed"
                            else "expert_repair_failed"
                            if event_type == "winning_quality_repair_failed"
                            else "expert_repair_queued"
                        ),
                        "expert_repair_agent_id": instance_id,
                        "expert_repair_merge_status": str(
                            details.get("status", "")
                        ),
                    },
                )
            continue
        if event_type == "winning_candidate_branch_created":
            swarm_event_seen = True
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            actor = str(row.get("actor", "")).strip()
            if hypothesis_id:
                candidate = update_candidate(
                    hypothesis_id,
                    {
                        "status": "created",
                        "mission_node": str(details.get("mission_node", "")),
                        "score": details.get("score"),
                        "created_sequence": row.get("sequence", 0),
                    },
                )
                if actor:
                    append_candidate_value(
                        hypothesis_id, "source_member_ids", actor
                    )
                    update_dynamic_agent(
                        actor,
                        {
                            "hypothesis_id": hypothesis_id,
                            "candidate_score": candidate.get("score"),
                            "ledger_status": "candidate_created",
                        },
                    )
            continue
        if event_type == "winning_candidate_ledger_frozen":
            swarm_event_seen = True
            ledger_projection = {
                "ledger_id": str(details.get("ledger_id", "")),
                "version": details.get("ledger_version", 0),
                "candidate_count": details.get("candidate_count", 0),
                "incremental": details.get("incremental") is True,
                "status": "active",
            }
            continue
        if event_type in {
            "winning_contribution_queued",
            "winning_contribution_rejected",
            "winning_contribution_rebase_required",
            "winning_contribution_merged",
        }:
            swarm_event_seen = True
            contribution_id = str(details.get("contribution_id", "")).strip()
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            merge_target = str(details.get("merge_target", ""))
            actor = str(row.get("actor", "")).strip()
            if hypothesis_id:
                append_candidate_value(
                    hypothesis_id, "merge_targets", merge_target
                )
                if actor:
                    append_candidate_value(
                        hypothesis_id, "source_member_ids", actor
                    )
                status = {
                    "winning_contribution_queued": "contribution_queued",
                    "winning_contribution_rejected": "contribution_rejected",
                    "winning_contribution_rebase_required": "rebase_required",
                    "winning_contribution_merged": "merged",
                }[event_type]
                update_candidate(
                    hypothesis_id,
                    {
                        "status": status,
                        "ledger_version": details.get(
                            "resulting_ledger_version",
                            details.get("to_version"),
                        ),
                        "last_merge_status": details.get("status", status),
                        "rejection_reason": str(details.get("reason", "")),
                    },
                )
            if contribution_id:
                receipt_id = f"event-{contribution_id}-{row.get('sequence', 0)}"
                merge_receipts_by_id[receipt_id] = {
                    "receipt_id": receipt_id,
                    "contribution_id": contribution_id,
                    "hypothesis_id": hypothesis_id,
                    "merge_target": merge_target,
                    "status": str(details.get("status") or event_type.removeprefix("winning_contribution_")),
                    "base_ledger_version": details.get(
                        "base_ledger_version", details.get("from_version")
                    ),
                    "resulting_ledger_version": details.get(
                        "resulting_ledger_version", details.get("to_version")
                    ),
                    "reason": str(details.get("reason", "")),
                }
                append_candidate_value(
                    hypothesis_id, "receipt_ids", receipt_id
                )
            continue
        if event_type == "winning_portfolio_merge_completed":
            swarm_event_seen = True
            selected_ids = safe_string_list(
                details.get("selected_hypothesis_ids", []), limit=8
            )
            rejected_ids = safe_string_list(
                details.get("rejected_hypothesis_ids", []), limit=16
            )
            portfolio_projection = {
                "ledger_id": str(details.get("ledger_id", "")),
                "ledger_version": details.get("ledger_version", 0),
                "selected_hypothesis_ids": selected_ids,
                "rejected_hypothesis_ids": rejected_ids,
                "final_equipment_portfolio": [
                    dict(item)
                    for item in details.get("final_equipment_portfolio", [])
                    if isinstance(item, dict)
                ][:7],
                "quality_gate": (
                    dict(details.get("portfolio_quality_gate", {}))
                    if isinstance(details.get("portfolio_quality_gate"), dict)
                    else {}
                ),
                "status": "completed",
            }
            portfolio_by_id = {
                str(item.get("hypothesis_id", "")): item
                for item in portfolio_projection["final_equipment_portfolio"]
                if str(item.get("hypothesis_id", "")).strip()
            }
            summary = details.get("swarm_summary", {})
            summary = summary if isinstance(summary, dict) else {}
            raw_ledger = summary.get("hypothesis_ledger", {})
            if isinstance(raw_ledger, dict):
                ledger_projection = {
                    "ledger_id": str(raw_ledger.get("ledger_id", "")),
                    "version": raw_ledger.get("version", 0),
                    "candidate_count": len(raw_ledger.get("hypotheses", []))
                    if isinstance(raw_ledger.get("hypotheses"), list)
                    else 0,
                    "status": str(raw_ledger.get("status", "active")),
                }
                for raw_candidate in raw_ledger.get("hypotheses", []):
                    if not isinstance(raw_candidate, dict):
                        continue
                    hypothesis_id = str(raw_candidate.get("hypothesis_id", ""))
                    if not hypothesis_id:
                        continue
                    update_candidate(
                        hypothesis_id,
                        {
                            "title": str(raw_candidate.get("title", ""))[:300],
                            "status": (
                                "selected_pending_verification"
                                if hypothesis_id in selected_ids
                                and str(
                                    portfolio_by_id.get(hypothesis_id, {}).get(
                                        "verification_status", ""
                                    )
                                ) == "pending"
                                else "selected"
                                if hypothesis_id in selected_ids
                                else "rejected"
                            ),
                            "s6_eligible": hypothesis_id in selected_ids,
                            "verification_status": str(
                                portfolio_by_id.get(hypothesis_id, {}).get(
                                    "verification_status", "assessed"
                                )
                            ),
                            "confidence_limited": bool(
                                portfolio_by_id.get(hypothesis_id, {}).get(
                                    "confidence_limited", False
                                )
                            ),
                            "selection_reason": (
                                "直接作战装备身份和Query因果成立；因对象证据、成熟度或对抗边界仍需核验，"
                                "按新质性与制胜价值补入S6，画像标记为待核验。"
                                if hypothesis_id in selected_ids
                                and str(
                                    portfolio_by_id.get(hypothesis_id, {}).get(
                                        "verification_status", ""
                                    )
                                ) == "pending"
                                else "经独立Codex按对象证据、Query因果、直接作战属性、"
                                "机制独立性与组合价值完成语义评审，进入本轮 S6 容量。"
                                if hypothesis_id in selected_ids
                                else "未进入本轮 S6 容量，保留为可展开查看的参考武器。"
                            ),
                            "score": raw_candidate.get("score"),
                            "equipment_forms": safe_string_list(
                                raw_candidate.get("equipment_forms", []), limit=8
                            ),
                            "changed_confrontation_variable": str(
                                raw_candidate.get("changed_confrontation_variable", "")
                            )[:300],
                            "mechanism_chain": safe_string_list(
                                raw_candidate.get("mechanism_chain", []), limit=6
                            ),
                            "direct_military_effects": safe_string_list(
                                raw_candidate.get("direct_military_effects", []), limit=6
                            ),
                            "project_function": str(
                                raw_candidate.get("project_function", "")
                            )[:300],
                            "reference_overview": str(
                                raw_candidate.get("reference_overview", "")
                            )[:1800],
                            "novelty_delta": str(
                                raw_candidate.get("novelty_delta", "")
                            )[:300],
                            "decisive_advantage_thesis": str(
                                raw_candidate.get("decisive_advantage_thesis", "")
                            )[:300],
                            "evidence_ids": safe_string_list(
                                raw_candidate.get("evidence_ids", []), limit=16
                            ),
                            "failure_boundaries": safe_string_list(
                                raw_candidate.get("failure_boundaries", []), limit=8
                            ),
                            "validation_plan": safe_string_list(
                                raw_candidate.get("validation_plan", []), limit=8
                            ),
                        },
                    )
            for raw_receipt in summary.get("merge_receipts", []):
                if not isinstance(raw_receipt, dict):
                    continue
                receipt_id = str(raw_receipt.get("receipt_id", ""))
                if not receipt_id:
                    continue
                merge_receipts_by_id[receipt_id] = {
                    key: raw_receipt.get(key)
                    for key in (
                        "receipt_id",
                        "contribution_id",
                        "hypothesis_id",
                        "merge_target",
                        "base_ledger_version",
                        "resulting_ledger_version",
                        "status",
                        "changed_fields",
                        "conflicts",
                        "quality_delta",
                        "rebase_required",
                    )
                }
                append_candidate_value(
                    str(raw_receipt.get("hypothesis_id", "")),
                    "receipt_ids",
                    receipt_id,
                )
            selected_id_set = set(selected_ids)
            rejected_id_set = set(rejected_ids)
            for member_id, member in dynamic_agents_by_id.items():
                hypothesis_id = str(member.get("hypothesis_id", "")).strip()
                if not hypothesis_id:
                    continue
                current_status = str(member.get("status", "planned")).lower()
                if (
                    hypothesis_id in selected_id_set
                    and current_status not in {"failed", "pruned", "skipped"}
                ):
                    update_dynamic_agent(
                        member_id,
                        {
                            "status": "merged",
                            "merge_status": "accepted",
                            "portfolio_status": "selected",
                            "last_event_type": event_type,
                            "last_sequence": row.get("sequence", 0),
                        },
                    )
                elif hypothesis_id in rejected_id_set:
                    update_dynamic_agent(
                        member_id,
                        {
                            "status": (
                                "completed"
                                if current_status == "merged"
                                else current_status
                            ),
                            "portfolio_status": "rejected",
                            "last_event_type": event_type,
                            "last_sequence": row.get("sequence", 0),
                        },
                    )
            continue
        if event_type in {
            "winning_model_queue_started",
            "winning_model_call_started",
            "winning_model_call_progress",
            "winning_model_call_completed",
        }:
            raw_steps = details.get("steps", [details.get("step")])
            raw_steps = raw_steps if isinstance(raw_steps, list) else [raw_steps]
            for raw_step in raw_steps:
                try:
                    step = int(raw_step)
                except (TypeError, ValueError):
                    continue
                if step not in latest_steps:
                    continue
                if latest_steps[step]["status"] != "completed":
                    latest_steps[step]["status"] = "running"
                latest_steps[step].update(
                    {
                        "current_step": str(details.get("current_step", "")),
                        "current_phase": str(details.get("phase", "")),
                        "elapsed_seconds": details.get("elapsed_seconds", 0),
                        "queue_wait_seconds": details.get(
                            "queue_wait_seconds", 0
                        ),
                        "runtime_agent_id": str(row.get("actor", "")),
                    }
                )
            continue
        if event_type in {
            "specialist_recruitment_planned",
            "specialist_spawned",
            "specialist_session_started",
            "specialist_session_completed",
            "specialist_completed",
            "specialist_pruned",
        }:
            swarm_event_seen = True
            dynamic_agent_id = str(
                details.get("agent_instance_id") or row.get("actor", "")
            ).strip()
            if dynamic_agent_id:
                swarm_member_ids.add(dynamic_agent_id)
                safe_fields = {
                    key: details.get(key)
                    for key in (
                        "task_id",
                        "agent_instance_id",
                        "display_name",
                        "archetype",
                        "role_purpose",
                        "trigger_residuals",
                        "wave",
                        "batch",
                        "hypothesis_id",
                        "merge_target",
                        "provider_type",
                        "execution_backend",
                        "context_isolation",
                        "provider_isolation_id",
                        "process_isolation",
                        "sandbox_mode",
                        "model",
                        "runtime_profile_id",
                        "role_contract_version",
                        "skill_ids",
                        "allow_child_spawn",
                        "expected_quality_gain",
                        "incremental_quality",
                        "session_ref",
                        "elapsed_seconds",
                    )
                }
                if event_type in {
                    "specialist_recruitment_planned",
                    "specialist_spawned",
                }:
                    safe_fields["recruitment_planned"] = True
                status = {
                    "specialist_recruitment_planned": "planned",
                    "specialist_spawned": "recruiting",
                    "specialist_session_started": "running",
                    "specialist_session_completed": (
                        "failed"
                        if str(details.get("status", "")).lower() == "failed"
                        else "completed"
                    ),
                    "specialist_completed": "completed",
                    "specialist_pruned": "pruned",
                }[event_type]
                safe_fields["status"] = status
                safe_fields["last_event_type"] = event_type
                safe_fields["last_sequence"] = row.get("sequence", 0)
                if event_type == "specialist_pruned":
                    safe_fields["prune_reason"] = str(
                        details.get("reason", "quality_or_dependency_gate")
                    )
                update_dynamic_agent(dynamic_agent_id, safe_fields)
            continue
        if event_type in {
            "hypothesis_created",
            "hypothesis_merged",
            "hypothesis_rejected",
            "swarm_gate_evaluated",
        }:
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            actor = str(row.get("actor", "")).strip()
            if event_type == "hypothesis_merged" and actor in swarm_member_ids:
                update_dynamic_agent(
                    actor,
                    {
                        "status": "merged",
                        "merge_status": "accepted",
                        "incremental_quality": details.get(
                            "incremental_quality"
                        ),
                        "contribution_id": details.get("contribution_id"),
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    },
                )
            elif event_type == "hypothesis_created" and actor in swarm_member_ids:
                update_dynamic_agent(
                    actor,
                    {
                        "ledger_status": "candidate_created",
                        "hypothesis_id": hypothesis_id,
                        "candidate_score": details.get("score"),
                    },
                )
            for member_id in swarm_member_ids:
                member = dynamic_agents_by_id.get(member_id, {})
                if not hypothesis_id or member.get("hypothesis_id") != hypothesis_id:
                    continue
                if event_type == "swarm_gate_evaluated":
                    update_dynamic_agent(
                        member_id,
                        {
                            "gate_stage": details.get("stage"),
                            "gate_passed": details.get("passed"),
                            "gate_score": details.get("score"),
                            "gate_residuals": details.get("residuals"),
                        },
                    )
                elif event_type == "hypothesis_rejected":
                    update_dynamic_agent(
                        member_id,
                        {
                            "hypothesis_status": "rejected",
                            "rejection_reasons": details.get(
                                "reasons", details.get("rejection_reasons", [])
                            ),
                        },
                    )
            continue
        if event_type not in {
            "winning_subagent_completed",
            "winning_reasoning_step_completed",
        }:
            continue
        if (
            event_type == "winning_subagent_completed"
            and details.get("execution_mode") == "dynamic"
        ):
            dynamic_agent_id = str(row.get("actor", "")).strip()
            if dynamic_agent_id:
                update_dynamic_agent(
                    dynamic_agent_id,
                    {
                        "display_name": str(
                            details.get("display_name", "动态专用 Agent")
                        ),
                        "merge_target": str(details.get("merge_target", "S3")),
                        "skill_ids": list(details.get("skill_ids", [])),
                        "knowledge_pack_ids": list(
                            details.get("knowledge_pack_ids", [])
                        ),
                        "status": _workflow_step_status(details),
                    },
                )
            continue
        try:
            step = int(details.get("step", 0))
        except (TypeError, ValueError):
            continue
        if step not in range(1, 7):
            continue
        actor = (
            str(row.get("actor", "")).strip()
            if event_type == "winning_subagent_completed"
            else ""
        )
        previous_middle_cycle = _positive_int(
            latest_steps[step].get("middle_cycle")
        )
        projected_middle_cycle = _positive_int(details.get("middle_cycle"))
        event_status = _workflow_step_status(details)
        event_execution_mode = str(details.get("execution_mode", "")).strip()
        preserve_skipped_projection = (
            latest_steps[step].get("status") == "skipped"
            and event_type == "winning_reasoning_step_completed"
        )
        if preserve_skipped_projection:
            event_status = "skipped"
            event_execution_mode = "skip"
        latest_steps[step].update(
            {
                "agent_id": actor or latest_steps[step]["agent_id"],
                "execution_mode": (
                    "skip"
                    if event_status == "skipped"
                    else event_execution_mode
                    or ("dynamic" if is_dynamic_profile else resolved_modes[step])
                ),
                "status": event_status,
                "decision_finalized": True,
                "middle_cycle": (
                    projected_middle_cycle or previous_middle_cycle
                ),
                "result_summary": (
                    latest_steps[step]["result_summary"]
                    if preserve_skipped_projection
                    else str(row.get("summary", ""))
                ),
            }
        )
    # Project live Dynamic-v2 Mission Graph activity back onto the canonical
    # S1-S6 cards.  Dynamic runs can intentionally skip the legacy sequential
    # S-Agent calls, so relying only on winning_subagent_completed leaves the
    # UI at 0/6 while multiple mission-node specialists are actively running.
    dynamic_terminal_statuses = {"completed", "merged", "pruned", "failed", "skipped"}
    dynamic_active_statuses = {"recruiting", "queued", "running"}
    for step in range(1, 7):
        if not mission_graph_projection:
            break
        mission_node = f"S{step}"
        members = [
            item
            for item in dynamic_agents_by_id.values()
            if str(item.get("mission_node") or item.get("merge_target"))
            == mission_node
            and item.get("archetype") != "quality_expert_judge"
            and not bool(item.get("inactive_capacity"))
        ]
        if not members:
            continue
        statuses = {str(item.get("status", "planned")).lower() for item in members}
        successful_count = sum(
            str(item.get("status", "")).lower() in {"completed", "merged"}
            for item in members
        )
        active_count = sum(
            str(item.get("status", "")).lower() in dynamic_active_statuses
            for item in members
        )
        latest_steps[step]["execution_mode"] = "dynamic"
        latest_steps[step]["decision_finalized"] = True
        latest_steps[step]["dynamic_instance_count"] = len(members)
        latest_steps[step]["dynamic_completed_count"] = successful_count
        latest_steps[step]["result_summary"] = (
            f"动态蜂群 {successful_count} / {len(members)} 个实例完成"
        )
        if active_count:
            latest_steps[step]["status"] = "running"
        elif statuses and statuses <= dynamic_terminal_statuses:
            if successful_count:
                latest_steps[step]["status"] = "completed"
            elif "failed" in statuses:
                latest_steps[step]["status"] = "failed"
            else:
                latest_steps[step]["status"] = "skipped"

    # Canonical S1-S6 progress is monotonic. A late residual challenger may
    # still contribute to an earlier merge node, but once a downstream node
    # has started it is misleading to make the stage card appear to return to
    # S3/S4/S5. The dynamic-agent ledger continues to expose that extra work.
    furthest_started_step = max(
        (
            int(node[1:])
            for item in dynamic_agents_by_id.values()
            if (node := str(item.get("mission_node") or item.get("merge_target")))
            in {f"S{step}" for step in range(1, 7)}
            and not bool(item.get("inactive_capacity"))
            and str(item.get("status", "planned")).lower() != "planned"
        ),
        default=0,
    )
    if furthest_started_step >= 3:
        for step in range(1, furthest_started_step):
            if latest_steps[step]["status"] not in {"failed", "skipped"}:
                latest_steps[step]["status"] = "completed"

    for row in rows:
        backtrack_step = _workflow_backtrack_step(row)
        if backtrack_step in latest_steps:
            latest_steps[backtrack_step]["backtrack_count"] += 1
    winning_stage_started = any(
        (
            str(row.get("actor", "")) == "winning_mechanism"
            and str(row.get("event_type", "")) in {"task_received", "tool_call"}
        )
        or str(row.get("event_type", ""))
        in {
            "winning_subagent_completed",
            "winning_reasoning_step_completed",
            "winning_mission_graph_planned",
            "winning_agent_instance_recruited",
            "winning_agent_instance_ready",
            "winning_agent_session_started",
            "winning_agent_session_completed",
        }
        for row in rows
    )
    winning_stage_finished = any(
        str(row.get("event_type", ""))
        in {
            "winning_stage_completed",
            "capability_image_created",
            "audit_completed",
            "report_completed",
        }
        for row in rows
    )
    if winning_stage_started and not winning_stage_finished and not is_dynamic_profile:
        step_dependencies: dict[int, tuple[int, ...]] = {
            1: (),
            2: (),
            3: (1, 2),
            4: (3,),
            5: (4,),
            6: (4, 5),
        }
        for step, dependencies in step_dependencies.items():
            if latest_steps[step]["status"] != "pending":
                continue
            if all(
                latest_steps[dependency]["status"] in {"completed", "skipped"}
                for dependency in dependencies
            ):
                latest_steps[step]["status"] = "running"
    step_plan = [latest_steps[step] for step in range(1, 7)]
    dynamic_agents = sorted(
        dynamic_agents_by_id.values(),
        key=lambda item: (
            _positive_int(item.get("wave")),
            _positive_int(item.get("batch")),
            str(item.get("agent_id", "")),
        ),
    )
    swarm_members = [
        item for item in dynamic_agents if item.get("agent_id") in swarm_member_ids
    ]
    supervisor_members = [
        item
        for item in swarm_members
        if item.get("archetype") == "quality_expert_judge"
    ]
    mission_members = [
        item
        for item in swarm_members
        if item.get("archetype") != "quality_expert_judge"
    ]
    provider_types = sorted(
        {
            str(item.get("provider_type", ""))
            for item in swarm_members
            if str(item.get("provider_type", ""))
        }
    )
    execution_backends = sorted(
        {
            str(item.get("execution_backend", ""))
            for item in swarm_members
            if str(item.get("execution_backend", ""))
        }
    )
    wave_numbers = sorted(
        {
            _positive_int(item.get("wave"))
            for item in swarm_members
            if _positive_int(item.get("wave")) > 0
        }
    )
    role_pools = [
        {
            "mission_node": node,
            "count": sum(
                item.get("mission_node") == node for item in mission_members
            ),
            "member_ids": [
                str(item.get("agent_id", ""))
                for item in mission_members
                if item.get("mission_node") == node
            ],
        }
        for node in ("S1", "S2", "S3", "S4", "S5", "S6")
    ]
    swarm_cluster = {
        "enabled": bool(swarm_event_seen or swarm_members),
        "policy_id": str(
            swarm_plan_details.get("policy_id")
            or (
                swarm_plan_details.get("plan", {}).get("policy", {}).get("policy_id")
                if isinstance(swarm_plan_details.get("plan"), dict)
                else ""
            )
            or "winning_swarm_quality_v1"
        ),
        "provider_type": (
            provider_types[0]
            if len(provider_types) == 1
            else "mixed"
            if provider_types
            else ""
        ),
        "execution_backend": (
            execution_backends[0]
            if len(execution_backends) == 1
            else "mixed"
            if execution_backends
            else ""
        ),
        "members": swarm_members,
        "supervisors": supervisor_members,
        "mission_graph": mission_graph_projection,
        "role_pools": role_pools,
        "dynamic_specialists": [
            item for item in mission_members if item.get("recruitment_planned")
        ],
        "candidate_lineage": sorted(
            candidate_lineage_by_id.values(),
            key=lambda item: (
                -float(item.get("score") or 0),
                str(item.get("hypothesis_id", "")),
            ),
        ),
        "hypothesis_ledger": ledger_projection,
        "merge_receipts": sorted(
            merge_receipts_by_id.values(),
            key=lambda item: (
                _positive_int(item.get("resulting_ledger_version")),
                str(item.get("receipt_id", "")),
            ),
        ),
        "portfolio_decision": portfolio_projection,
        "final_equipment_portfolio": list(
            portfolio_projection.get("final_equipment_portfolio", [])
        ),
        "waves": [
            {
                "wave": wave,
                "label": {
                    1: "广度探索",
                    2: "定向挑战",
                    3: "收敛决策",
                }.get(wave, f"波次 {wave}"),
                "member_ids": [
                    str(item.get("agent_id", ""))
                    for item in mission_members
                    if _positive_int(item.get("wave")) == wave
                ],
            }
            for wave in wave_numbers
        ],
        "counts": {
            # Read-only quality judges supervise convergence but do not consume
            # Mission Graph instance capacity and must not make the UI appear
            # to exceed maximum_instances.
            "total": len(mission_members),
            "planned": sum(
                bool(item.get("recruitment_planned")) for item in mission_members
            ),
            "recruiting": sum(
                item.get("status") == "recruiting" for item in mission_members
            ),
            "running": sum(
                item.get("status") == "running" for item in mission_members
            ),
            "completed": sum(
                item.get("status") == "completed" for item in mission_members
            ),
            "merged": sum(
                item.get("status") == "merged" for item in mission_members
            ),
            "pruned": sum(
                item.get("status") == "pruned" for item in mission_members
            ),
            "failed": sum(
                item.get("status") == "failed" for item in mission_members
            ),
        },
    }
    skipped_agent_ids = {
        str(definition["agent_id"])
        for definition in WINNING_STEP_DEFINITIONS
        if latest_steps[int(definition["step"])]["status"] == "skipped"
        or latest_steps[int(definition["step"])]["execution_mode"] == "skip"
    }
    active_agent_ids: list[str] = []
    for row in rows:
        row_details = row.get("details", {})
        skipped_step = (
            row.get("event_type") == "winning_subagent_completed"
            and isinstance(row_details, dict)
            and (
                row_details.get("execution_mode") == "skip"
                or row_details.get("status") == "skipped_by_branch_blueprint"
            )
        )
        actor = str(row.get("actor", "")).strip()
        if (
            not skipped_step
            and actor
            and actor != "unknown"
            and actor not in skipped_agent_ids
            and actor not in active_agent_ids
        ):
            active_agent_ids.append(actor)
        target = (
            str(row_details.get("target_agent_id", "")).strip()
            if isinstance(row_details, dict)
            else ""
        )
        if (
            target
            and target not in skipped_agent_ids
            and target not in active_agent_ids
        ):
            active_agent_ids.append(target)
    phases = _interaction_workflow_phases(
        rows,
        view=view,
        step_plan=step_plan,
        dynamic_agents=dynamic_agents,
    )
    terminal_failure = next(
        (
            row
            for row in reversed(rows)
            if row.get("event_type") == "run_failed"
        ),
        {},
    )
    terminal_failure_details = terminal_failure.get("details", {})
    terminal_failure_details = (
        terminal_failure_details
        if isinstance(terminal_failure_details, dict)
        else {}
    )
    failure_detail = str(
        terminal_failure_details.get("error")
        or getattr(view, "error", "")
        or ""
    ).strip()
    failed_phase = next(
        (item["id"] for item in phases if item.get("status") == "failed"),
        "",
    )
    run_is_failed = str(getattr(view, "status", "")).lower() == "failed"
    if not run_is_failed:
        # Historical failures remain in the audit timeline, but an active
        # resume must not present them as the current workflow failure.
        failed_phase = ""
        failure_detail = ""
    raw_step_mode_changes = meta_details.get("step_mode_changes", [])
    step_mode_changes = (
        [dict(item) for item in raw_step_mode_changes if isinstance(item, dict)]
        if isinstance(raw_step_mode_changes, list)
        else []
    )
    if not step_mode_changes:
        for item in meta_details.get("step_mode_overrides", []):
            if not isinstance(item, dict):
                continue
            try:
                step = int(item.get("step", 0))
            except (TypeError, ValueError):
                continue
            mode = str(item.get("mode", ""))
            if step not in pre_l4_modes or mode not in {
                "skip", "light", "standard", "deep"
            }:
                continue
            step_mode_changes.append(
                {
                    "step": step,
                    "previous_mode": pre_l4_modes[step],
                    "mode": mode,
                    **(
                        {"reason": str(item["reason"])}
                        if str(item.get("reason", "")).strip()
                        else {}
                    ),
                }
            )
    stage_gates: list[dict] = []
    for layer in ("L1", "L2", "L3"):
        row = next(
            (
                item
                for item in reversed(rows)
                if item.get("event_type")
                in {"winning_stage_completed", "winning_stage_reused"}
                and str(item.get("summary", "")).upper().startswith(layer)
            ),
            None,
        )
        if row is None:
            continue
        summary = str(row.get("summary", ""))
        stage_gates.append(
            {
                "layer": layer,
                "gate_passed": "gate=true" in summary.lower(),
                "summary": summary,
            }
        )
    return {
        "status": str(getattr(view, "status", "")),
        "execution": {
            "profile_id": execution_profile_id,
            "mode": str(started_details.get("mode") or execution.get("mode") or ""),
            "provider": str(
                started_details.get("provider")
                or execution.get("provider")
                or ""
            ),
            "model": str(started_details.get("model") or execution.get("model") or ""),
            "base_url_host": str(started_details.get("base_url_host", "")),
        },
        "discovery": {
            "primary_branch": primary_branch,
            "branch_name": str(
                blueprint.get("branch_name")
                or (
                    BRANCH_BLUEPRINTS[primary_branch].name
                    if primary_branch in BRANCH_BLUEPRINTS
                    else "Agent 正在分析主分支"
                )
            ),
            "secondary_branches": list(
                meta_details.get("secondary_branches")
                or blueprint.get("secondary_branches", [])
            ),
            "blueprint_mode": str(blueprint.get("blueprint_mode", "")),
            "generated_by": str(blueprint.get("generated_by", "")),
            "confidence": blueprint.get("confidence"),
            "baseline_agent_plan": list(blueprint.get("baseline_agent_plan", [])),
            "callback_agent_ids": list(blueprint.get("callback_agent_ids", [])),
        },
        "l4": {
            "cycle": meta_details.get("cycle", len(meta_events)),
            "replan_required": meta_details.get("replan_required") is True,
            "added_secondary_branches": list(
                meta_details.get("added_secondary_branches", [])
            ),
            "step_mode_overrides": list(
                meta_details.get("step_mode_overrides", [])
            ),
            "step_mode_changes": step_mode_changes,
            "dynamic_subagents": list(meta_details.get("dynamic_subagents", [])),
            "focus_questions": list(meta_details.get("focus_questions", [])),
            "rationale": str(meta_details.get("rationale", "")),
            "stop_reason": str(meta_details.get("stop_reason", "")),
        },
        "step_plan": step_plan,
        "dynamic_agents": dynamic_agents,
        "swarm_cluster": swarm_cluster,
        "stage_gates": stage_gates,
        "phases": phases,
        "failure": {
            "phase": "" if run_has_complete_report else failed_phase,
            "detail": "" if run_has_complete_report else failure_detail,
        },
        "loops": {
            "inner": sum(
                row.get("event_type") == "winning_inner_loop_evaluated"
                for row in rows
            ),
            "middle": sum(
                row.get("event_type") == "winning_middle_loop_evaluated"
                for row in rows
            ),
            "outer": sum(
                row.get("event_type") == "winning_outer_loop_evaluated"
                for row in rows
            ),
            "meta": len(meta_events),
        },
        "active_agent_ids": active_agent_ids,
    }


def _workflow_step_status(details: dict) -> str:
    raw_status = str(details.get("status", "completed")).lower()
    if (
        details.get("execution_mode") == "skip"
        or raw_status in {"skipped", "skipped_by_branch_blueprint"}
    ):
        return "skipped"
    if raw_status in {"failed", "error", "cancelled"}:
        return "failed"
    if raw_status in {"pending", "running"}:
        return raw_status
    return "completed"


def _workflow_backtrack_step(row: dict) -> int:
    details = row.get("details", {})
    if not isinstance(details, dict):
        return 0
    event_type = str(row.get("event_type", ""))
    if event_type == "recall_requested":
        return _workflow_target_step(details)
    if details.get("passed") is not False:
        return 0
    next_action = details.get("next_action", {})
    next_action = next_action if isinstance(next_action, dict) else {}
    action = str(
        details.get("recommended_action")
        or details.get("action")
        or next_action.get("action")
        or ("rerun" if details.get("rerun_from_step") else "")
    ).lower()
    if action not in {"retry", "recall", "backtrack", "rerun"}:
        return 0
    return _workflow_target_step(details)


def _workflow_target_step(details: dict) -> int:
    next_action = details.get("next_action", {})
    next_action = next_action if isinstance(next_action, dict) else {}
    candidates = (
        details.get("backtrack_to_step"),
        details.get("rerun_from_step"),
        details.get("target_step"),
        next_action.get("target_step"),
        details.get("step"),
    )
    for value in candidates:
        try:
            step = int(value or 0)
        except (TypeError, ValueError):
            continue
        if step in range(1, 7):
            return step
    node = str(
        details.get("return_node") or details.get("source_layer") or ""
    ).upper()
    if node.startswith("S") and node[1:].isdigit():
        step = int(node[1:])
        return step if step in range(1, 7) else 0
    return {"L1": 1, "L2": 4, "L3": 5}.get(node, 0)


def _positive_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _interaction_workflow_phases(
    rows: list[dict],
    *,
    view: object,
    step_plan: list[dict],
    dynamic_agents: list[dict],
) -> list[dict]:
    event_types = [str(row.get("event_type", "")) for row in rows]
    event_type_set = set(event_types)

    def has_actor_activity(actor_id: str) -> bool:
        return any(
            str(row.get("actor", "")) == actor_id
            and row.get("event_type") in {
                "agent_task_delegated",
                "task_received",
                "tool_call",
                "tool_result",
            }
            for row in rows
        )

    def phase(
        phase_id: str,
        label: str,
        status: str,
        agent_ids: list[str],
        relevant_types: set[str],
    ) -> dict:
        return {
            "id": phase_id,
            "label": label,
            "status": status,
            "agent_ids": list(dict.fromkeys(agent_ids)),
            "event_count": sum(item in relevant_types for item in event_types),
        }

    baseline_result_agents = {
        str(row.get("actor", ""))
        for row in rows
        if row.get("event_type") == "baseline_result"
        and str(row.get("actor", "")).strip()
    }
    selected_baseline_agents = {
        str(agent_id)
        for agent_id in getattr(view, "selected_agent_ids", [])
        if str(agent_id).strip()
    }
    # A savepoint-bearing baseline result is durable work even when the worker
    # stops before it emits the later batch-summary event.
    baseline_results_complete = bool(baseline_result_agents) and (
        not selected_baseline_agents
        or selected_baseline_agents.issubset(baseline_result_agents)
    )
    blueprint_completed = (
        "discovery_meta_loop_evaluated" in event_type_set
        or baseline_results_complete
    )
    # The worker marks the run as researching before the orchestrator model has
    # returned the discovery blueprint. During that first model call there is
    # intentionally no run_started trace yet, but the UI must still show real
    # activity instead of leaving every phase pending and looking stalled.
    run_status = str(getattr(view, "status", "")).lower()
    blueprint_started = "run_started" in event_type_set or run_status in {
        "planning",
        "researching",
        "recalling",
        "synthesizing",
        "reviewing",
        "reporting",
    }
    baseline_completed = bool(
        event_type_set
        & {
            "baseline_agents_summarized",
            "discovery_convergence_completed",
            "winning_subagent_completed",
            "audit_completed",
            "report_completed",
        }
    ) or baseline_results_complete
    baseline_started = bool(
        event_type_set
        & {
            "baseline_pipeline_started",
            "baseline_discovery_started",
            "baseline_discovery_lane_started",
            "baseline_model_queue_started",
            "baseline_model_call_started",
            "baseline_model_call_progress",
            "baseline_discovery_completed",
            "baseline_analysis_started",
            "baseline_wave_started",
            "baseline_wave_completed",
            "baseline_agent_completed",
            "baseline_result",
        }
    ) or bool(baseline_result_agents)
    convergence_completed = bool(
        event_type_set
        & {
            "discovery_convergence_completed",
            "winning_subagent_completed",
            "audit_completed",
            "report_completed",
        }
    )
    convergence_started = has_actor_activity("convergence_fusion")
    executable_steps = [
        item for item in step_plan if item["execution_mode"] != "skip"
    ]
    # A completed first pass is not the end of the S-Agent phase: the middle
    # critic may still be reviewing the chain or running a targeted S4/S6
    # repair. Only close the phase after its loop/stage gate is persisted.
    # Otherwise the UI can show "completed" for several minutes while a real
    # model call is still active.
    s_agent_gate_completed = bool(
        event_type_set
        & {
            "winning_middle_loop_evaluated",
            "winning_stage_completed",
            "winning_stage_reused",
            "winning_portfolio_merge_completed",
            "capability_image_created",
            "audit_completed",
            "report_completed",
        }
    )
    s_agents_completed = (
        bool(executable_steps)
        and all(item["status"] == "completed" for item in executable_steps)
        and s_agent_gate_completed
    )
    if event_type_set & {"audit_completed", "report_completed"}:
        s_agents_completed = True
    s_agents_started = bool(
        event_type_set
        & {
            "winning_subagent_completed",
            "winning_model_queue_started",
            "winning_model_call_started",
            "winning_model_call_progress",
            "winning_model_call_completed",
            "winning_inner_loop_evaluated",
            "winning_middle_loop_evaluated",
            "winning_outer_loop_evaluated",
            "winning_mission_graph_planned",
            "winning_agent_instance_recruited",
            "winning_agent_instance_ready",
            "winning_agent_session_started",
            "winning_agent_session_completed",
            "winning_portfolio_merge_completed",
        }
    ) or has_actor_activity("winning_mechanism")
    if s_agents_started:
        # S1–S6 only starts after baseline material has converged. Older runs
        # can miss the explicit convergence event when an exception interrupts
        # checkpoint persistence, so preserve the causal progression in replay.
        convergence_completed = True
    audit_completed = bool(event_type_set & {"audit_completed", "report_completed"})
    audit_started = has_actor_activity("auditor")
    report_status = "pending"
    report_started = False
    report_failure_detail = ""
    for row in rows:
        event_type = str(row.get("event_type", ""))
        actor = str(row.get("actor", ""))
        details = row.get("details", {})
        details = details if isinstance(details, dict) else {}
        targets_reporter = (
            event_type == "agent_task_delegated"
            and str(details.get("target_agent_id", "")) == "reporter"
        )
        reporter_activity = actor == "reporter" and (
            event_type
            in {
                "task_received",
                "tool_call",
                "tool_result",
            }
            or event_type.startswith("report_model_")
        )
        if targets_reporter or reporter_activity:
            report_started = True
            report_status = "running"
            report_failure_detail = ""
        if event_type == "report_model_failed":
            report_started = True
            report_status = "failed"
            report_failure_detail = str(
                details.get("detail") or details.get("reason") or ""
            ).strip()
        elif event_type == "report_completed":
            report_started = True
            report_status = "completed"
            report_failure_detail = ""
    # Some configuration or delivery failures can stop the run after Reporter
    # activity but before the explicit report_model_failed trace is persisted.
    # Project those terminal failures as failed instead of leaving the phase
    # looking permanently active.
    # A persisted report and an approved/completed run are authoritative even
    # when a late worker writes a stale report_model_failed event or failure
    # marker. Never show a successful delivery as failed.
    run_view = view
    run_result = getattr(run_view, "result", {})
    run_result = run_result if isinstance(run_result, dict) else {}
    run_has_complete_report = (
        str(getattr(run_view, "status", "")).lower() == "completed"
        and (
            str(run_result.get("audit_status", "")).lower() in {"approved", "passed"}
            or bool(run_result.get("report_available"))
        )
    )
    if run_status == "failed" and report_started and report_status != "completed" and not run_has_complete_report:
        report_status = "failed"
    if run_has_complete_report:
        report_status = "completed"
        report_failure_detail = ""
    baseline_agents = [
        str(agent_id)
        for row in rows
        if row.get("event_type") in {
            "run_started",
            "baseline_pipeline_started",
            "baseline_wave_started",
            "baseline_wave_completed",
        }
        and isinstance(row.get("details"), dict)
        for agent_id in row["details"].get("agent_ids", [])
        if str(agent_id).strip()
    ]
    if not baseline_agents:
        baseline_agents = [
            str(item) for item in getattr(view, "selected_agent_ids", [])
        ]
    s_agent_ids = [
        str(item["agent_id"])
        for item in step_plan
        if item["execution_mode"] != "skip" and item["status"] != "skipped"
    ]
    s_agent_ids.extend(
        str(item.get("agent_id", ""))
        for item in dynamic_agents
        if item.get("status") not in {"skipped", "pruned", "failed"}
    )
    latest_report_progress = next(
        (
            row
            for row in reversed(rows)
            if str(row.get("event_type", ""))
            in {
                "report_model_queue_started",
                "report_model_call_started",
                "report_model_call_progress",
                "report_model_call_completed",
            }
        ),
        {},
    )
    latest_report_details = latest_report_progress.get("details", {})
    latest_report_details = (
        latest_report_details
        if isinstance(latest_report_details, dict)
        else {}
    )
    report_progress_detail = ""
    if report_status == "running" and latest_report_details:
        current_step = str(
            latest_report_details.get("current_step", "三层九项报告撰写")
        )
        elapsed_seconds = float(
            latest_report_details.get("elapsed_seconds", 0) or 0
        )
        report_progress_detail = current_step
        if elapsed_seconds > 0:
            report_progress_detail += f" · 已耗时 {round(elapsed_seconds)} 秒"

    phases = [
        phase(
            "blueprint",
            "任务理解与发现蓝图",
            "completed" if blueprint_completed else "running" if blueprint_started else "pending",
            ["orchestrator"],
            {"run_started", "discovery_meta_loop_evaluated"},
        ),
        phase(
            "baseline",
            "多源基线研究",
            "completed" if baseline_completed else "running" if baseline_started else "pending",
            baseline_agents,
            {
                "baseline_wave_started",
                "baseline_wave_completed",
                "baseline_agent_completed",
                "baseline_agents_summarized",
                "baseline_pipeline_started",
                "baseline_discovery_started",
                "baseline_discovery_lane_started",
                "baseline_model_queue_started",
                "baseline_model_call_started",
                "baseline_model_call_progress",
                "baseline_model_call_completed",
                "baseline_discovery_completed",
                "baseline_analysis_started",
                "baseline_analysis_completed",
                "baseline_materialization_progress",
            },
        ),
        phase(
            "convergence",
            "发现结果收敛",
            "completed" if convergence_completed else "running" if convergence_started else "pending",
            ["convergence_fusion"],
            {"discovery_convergence_completed"},
        ),
        phase(
            "s_agents",
            "S1-S6 专用 Agent",
            "completed" if s_agents_completed else "running" if s_agents_started else "pending",
            s_agent_ids,
            {
                "winning_subagent_completed",
                "winning_model_queue_started",
                "winning_model_call_started",
                "winning_model_call_progress",
                "winning_model_call_completed",
                "winning_inner_loop_evaluated",
                "winning_middle_loop_evaluated",
                "winning_outer_loop_evaluated",
                "winning_mission_graph_planned",
                "winning_agent_instance_recruited",
                "winning_agent_instance_ready",
                "winning_agent_session_started",
                "winning_agent_session_completed",
                "winning_portfolio_merge_completed",
            },
        ),
        phase(
            "audit",
            "独立审计",
            "completed" if audit_completed else "running" if audit_started else "pending",
            ["auditor"],
            {"audit_completed"},
        ),
        {
            **phase(
                "report",
                "报告交付",
                report_status,
                ["reporter"],
                {
                    "report_model_queue_started",
                    "report_model_call_started",
                    "report_model_call_progress",
                    "report_model_call_completed",
                    "report_completed",
                    "report_model_failed",
                },
            ),
            "detail": (
                "独立报告生成失败，未使用降级模板；可从检查点恢复"
                if report_status == "failed"
                else report_progress_detail
            ),
            "error": report_failure_detail,
        },
    ]
    if run_status in {"failed", "cancelled"} and not run_has_complete_report:
        phase_order = ["blueprint", "baseline", "convergence", "s_agents", "audit", "report"]
        started = {
            "blueprint": blueprint_started,
            "baseline": baseline_started,
            "convergence": convergence_started or convergence_completed,
            "s_agents": s_agents_started,
            "audit": audit_started,
            "report": report_started,
        }
        active_phase = next(
            (phase_id for phase_id in reversed(phase_order) if started[phase_id]),
            "blueprint",
        )
        for phase_row in phases:
            if phase_row["id"] == active_phase:
                phase_row["status"] = "failed" if run_status == "failed" else "cancelled"
                if active_phase != "report":
                    phase_row["detail"] = "运行在此阶段停止；已保留可恢复检查点"
            elif phase_row["id"] in {"blueprint", "baseline", "convergence", "s_agents", "audit", "report"}:
                phase_row["status"] = (
                    "completed"
                    if phase_order.index(phase_row["id"])
                    < phase_order.index(active_phase)
                    else "pending"
                )
    return phases


def _interaction_agents_with_runtime(
    configured_agents: list[dict],
    rows: list[dict],
) -> list[dict]:
    result = [dict(item) for item in configured_agents]
    known_ids = {str(item.get("agent_id", "")) for item in result}
    for row in rows:
        if row.get("event_type") != "winning_subagent_completed":
            continue
        details = row.get("details", {})
        actor = str(row.get("actor", ""))
        if (
            not isinstance(details, dict)
            or details.get("execution_mode") != "dynamic"
            or not actor
            or actor in known_ids
        ):
            continue
        known_ids.add(actor)
        result.append(
            {
                "agent_id": actor,
                "display_name": str(
                    details.get("display_name", "动态专用 Agent")
                ),
                "description": "由 Codex L4/蓝图按专业缺口生成并在受控 Harness 中执行。",
                "capability_tags": [],
                "tools": [],
                "visible_sections": [],
                "skills": [],
                "skill_ids": list(details.get("skill_ids", [])),
                "shared_skills": [],
                "knowledge_pack_ids": list(
                    details.get("knowledge_pack_ids", [])
                ),
                "knowledge_packs": [],
                "harness_profile": "dynamic_specialist_v1",
                "harness_profile_config": {},
                "system_agent": False,
                "output_contract": "bounded_dynamic_specialist_result",
                "research_policy": {},
                "handoff_policy": {
                    "publish_to": [str(details.get("merge_target", "S3"))]
                },
                "runtime_dynamic": True,
            }
        )
    return result


def _require_role(role: str, allowed: set[str]) -> None:
    if role not in allowed:
        raise HTTPException(status_code=403, detail="insufficient role")


def _run_file(service: ResearchApplicationService, output_root: Path, run_id: str, relative: str) -> Path:
    root = _run_root(service, output_root, run_id)
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="run output not found")
    return path


def _is_historical_snapshot(view: object) -> bool:
    """True when metadata was restored without the original run artifacts."""
    result = getattr(view, "result", {})
    result = result if isinstance(result, dict) else {}
    recovery = result.get("recovery", {})
    return (
        isinstance(recovery, dict)
        and recovery.get("run_artifacts_present") is False
    )


def _historical_snapshot_report(view: object) -> str:
    topic = str(getattr(view, "topic", "本次研究任务"))
    recovery = getattr(view, "result", {}) or {}
    recovery = recovery.get("recovery", {}) if isinstance(recovery, dict) else {}
    source = str(recovery.get("source", "历史任务快照")) if isinstance(recovery, dict) else "历史任务快照"
    return (
        f"# {topic}\n\n"
        "> 这是可审计的历史任务快照。原始研究产物目录未随快照保存，系统未伪造报告正文、证据或能力画像。\n\n"
        f"- 快照来源：{source}\n"
        "- 当前可用：任务主题、运行状态、审计元数据与历史交互索引\n"
        "- 详细报告、证据卡和能力画像：原始产物恢复后自动可读；也可重新运行任务生成完整产物。"
    )


def _preferred_report_path(run_root: Path) -> Path | None:
    """Return the approved postfix report when present, otherwise the original.

    Postfix regeneration intentionally preserves ``report.md`` for auditability.
    The review and benchmark read paths should expose the repaired artifact only
    when its companion quality gate explicitly passed.
    """

    root = run_root.resolve()
    postfix_path = (root / "report-postfix.md").resolve()
    postfix_gate_path = (root / "report-quality-gate-postfix.json").resolve()
    if (
        root in postfix_path.parents
        and root in postfix_gate_path.parents
        and postfix_path.is_file()
        and postfix_gate_path.is_file()
    ):
        try:
            gate = json.loads(postfix_gate_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            gate = {}
        if gate.get("passed") is True:
            return postfix_path

    report_path = (root / "report.md").resolve()
    if root in report_path.parents and report_path.is_file():
        return report_path
    return None


def _run_root(service: ResearchApplicationService, output_root: Path, run_id: str) -> Path:
    try:
        view = service.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    root = _resolve_run_root(output_root, run_id, view.result)
    if root is None:
        run_dir_value = str(view.result.get("run_dir", "")).strip()
        if run_dir_value:
            raise HTTPException(status_code=404, detail="run output not found")
        raise HTTPException(status_code=409, detail="run outputs are not ready")
    if not root.is_dir() or root.is_symlink():
        raise HTTPException(status_code=404, detail="run output not found")
    return root


def _read_json(service: ResearchApplicationService, output_root: Path, run_id: str, relative: str):
    return json.loads(_run_file(service, output_root, run_id, relative).read_text(encoding="utf-8"))


def _read_jsonl(service: ResearchApplicationService, output_root: Path, run_id: str, relative: str) -> list[dict]:
    return _jsonl_path(_run_file(service, output_root, run_id, relative))


def _is_safe_run_id(run_id: str) -> bool:
    return bool(run_id) and "/" not in run_id and "\\" not in run_id and ".." not in run_id


def _resolve_run_root(
    output_root: Path,
    run_id: str,
    result: dict | None = None,
) -> Path | None:
    if not _is_safe_run_id(run_id):
        raise HTTPException(status_code=400, detail="invalid run id")
    primary = (output_root.resolve() / run_id)
    candidates = [primary]
    if isinstance(result, dict):
        legacy_value = str(result.get("run_dir", "")).strip()
        if legacy_value:
            candidates.append(Path(legacy_value).expanduser())
    for candidate in candidates:
        try:
            if not candidate.is_dir() or candidate.is_symlink():
                continue
            return candidate.resolve()
        except OSError:
            continue
    return None


def _public_run_result(result: object, output_root: Path, run_id: str) -> dict:
    data = dict(result) if isinstance(result, dict) else {}
    root = _resolve_run_root(output_root, run_id, data)
    public = {
        key: value
        for key, value in data.items()
        if key not in {
            "run_dir",
            "report_path",
            "summary_path",
            "capability_images_path",
            "manifest_path",
            "branch_deliverables_path",
        }
    }
    public["report_available"] = bool(
        root is not None and _preferred_report_path(root) is not None
    )
    public["historical_snapshot"] = bool(
        isinstance(data.get("recovery"), dict)
        and data["recovery"].get("run_artifacts_present") is False
    )
    return public


def _public_run_view(view: object, output_root: Path) -> dict:
    data = dict(view.__dict__) if hasattr(view, "__dict__") else dict(view)
    run_id = str(data.get("run_id", ""))
    data["result"] = _public_run_result(data.get("result"), output_root, run_id)
    return data


def _jsonl_path(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _delete_run_output(output_root: Path, run_id: str) -> None:
    if not run_id.startswith("run-") or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(status_code=400, detail="invalid run id")
    root = output_root.resolve()
    target = root / run_id
    if target.is_symlink():
        target.unlink()
        return
    if not target.exists():
        return
    if target.resolve().parent != root:
        raise HTTPException(status_code=400, detail="invalid run output path")
    shutil.rmtree(target)


def _verify_run_deleted(
    service: ResearchApplicationService,
    output_root: Path,
    run_id: str,
) -> None:
    residue: dict[str, int | bool] = {}
    try:
        service.get_run(run_id)
    except (KeyError, NoResultFound):
        pass
    else:
        residue["run"] = True

    inspect_residue = getattr(service.repository, "deletion_residue", None)
    if callable(inspect_residue):
        residue.update(
            {
                name: count
                for name, count in inspect_residue(run_id).items()
                if count
            }
        )

    target = output_root.resolve() / run_id
    if target.exists() or target.is_symlink():
        residue["run_output"] = True
    if residue:
        raise RuntimeError(f"permanent deletion left backend residue: {residue}")


def _capability_api_view(row: dict) -> dict:
    """Enrich v1 capability images for the normative UI without mutating artifacts."""
    result = dict(row)
    for prose_field in ("capability_image", "deep_capability_portrait"):
        if prose_field in result:
            result[prose_field] = strip_schema_placeholders(result[prose_field])
    for removed_field in (
        "key_functions",
        "performance_indicators",
        "verification_methods",
    ):
        result.pop(removed_field, None)
    structured = any(
        result.get(key)
        for key in (
            "military_utility",
            "strike_countermeasure_value",
            "novelty",
            "foresight",
            "evidence_basis",
            "agent_contributions",
            "reasoning_refs",
        )
    )
    result["analysis_provenance_status"] = (
        "structured" if structured else "legacy_derived"
    )
    upgrade = result.get("capability_type") == "upgrade"
    image = str(result.get("capability_image", ""))
    if not result.get("equipment_form"):
        result["equipment_form"] = str(result.get("equipment_category", ""))
    if not result.get("operational_mechanism"):
        result["operational_mechanism"] = (
            _capability_labeled_value(image, "深度机制")
            or str(result.get("strike_countermeasure_value", ""))
        )
    if not result.get("development_path"):
        result["development_path"] = str(result.get("foresight", ""))
    if not result.get("mission_effect"):
        result["mission_effect"] = str(
            result.get("strike_countermeasure_value")
            or result.get("military_utility")
            or (
                "以较短工程周期提升现役装备在复杂环境中的体系贡献度、任务适配性和持续保障能力。"
                if upgrade
                else "形成可组合、可扩展、可降级的新型任务能力，缩短从发现问题到产生任务效果的闭环。"
            )
        )
    if not result.get("system_dependencies"):
        result["system_dependencies"] = ["与现有指挥信息、情报侦察和保障体系形成标准化接口", "支持通信受限和局部节点失效条件下的降级运行"]
    if not result.get("risk_boundaries"):
        result["risk_boundaries"] = ["公开证据不足的参数保留区间与置信度，不转化为确定阈值", "不以单一平台性能替代体系任务效果，不假设持续高带宽连接"]
    source_name = str(result.get("name", "")).strip()
    equipment_form = str(
        result.get("equipment_form") or result.get("equipment_category") or ""
    ).strip()
    display_name = source_name or primary_equipment_form_title(equipment_form)
    if source_name and display_name != source_name:
        result["source_name"] = source_name
    result["name"] = display_name
    equipment_identity = "；".join(
        str(value)
        for value in (
            display_name,
            result.get("equipment_form") or result.get("equipment_category"),
            result.get("mission_effect") or result.get("military_utility"),
        )
        if str(value).strip()
    )
    result["problem_statement"] = normalize_capability_problem(
        result.get("capability_gap") or result.get("problem_statement"),
        fallback=f"{display_name}对应的关键任务链存在目标、授权、交战或毁伤评估断点",
    )
    result["operational_process"] = complete_operational_process(
        result.get("operational_process") or result.get("strike_chain_contribution"),
        equipment_identity=equipment_identity,
    )
    result["verification_plan"] = normalize_verification_plan(
        result.get("verification_plan") or result.get("verification"),
        equipment_identity=equipment_identity,
        failure_boundary=(
            result.get("risk_boundaries")
            or result.get("operational_constraints")
            or result.get("upgrade_boundary")
        ),
    )
    portrait_scenario = result.get("target_scenario") or result.get("related_scenario")
    authored_portrait = str(
        result.get("deep_capability_portrait")
        or result.get("capability_image")
        or ""
    ).strip()
    result["deep_capability_portrait"] = _remove_raw_query_from_portrait_lede(
        authored_portrait,
        scenario=portrait_scenario,
    )
    return result


def _provisional_s6_capability_rows(portfolio: object) -> list[dict]:
    """Expose completed S6 selections while the final delivery file is pending.

    S6 freezes the selected equipment portfolio before the reporter writes
    ``capability_images.json``.  The portfolio already contains the reviewed
    mechanism, evidence references, failure boundaries and validation path, so
    hiding it until report delivery incorrectly makes completed S6 work appear
    as a reference-only candidate list.
    """

    if not isinstance(portfolio, list):
        return []
    rows: list[dict] = []
    for index, item in enumerate(portfolio, start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        equipment_form = str(item.get("equipment_form", "")).strip()
        function = str(item.get("function", "")).strip()
        mechanism = str(item.get("operational_mechanism", "")).strip()
        military_value = str(item.get("military_value", "")).strip()
        development_path = str(item.get("development_path", "")).strip()
        failure_boundary = str(item.get("failure_boundary", "")).strip()
        if not name or not equipment_form:
            continue
        hypothesis_id = str(item.get("hypothesis_id", "")).strip()
        raw_evidence_ids = item.get("direct_evidence_refs", [])
        evidence_ids = (
            [str(value).strip() for value in raw_evidence_ids if str(value).strip()][:12]
            if isinstance(raw_evidence_ids, list)
            else []
        )
        capability_id = (
            f"s6-{hypothesis_id}" if hypothesis_id else f"s6-portfolio-{index:02d}"
        )
        portrait = str(
            item.get("deep_capability_portrait")
            or item.get("capability_portrait")
            or item.get("capability_image")
            or ""
        ).strip()
        rows.append(
            {
                "capability_id": capability_id,
                "name": name,
                "equipment_category": equipment_form,
                "equipment_form": equipment_form,
                "capability_type": str(item.get("type", "new_capability")),
                "source_winning_logic": mechanism or military_value,
                "related_scenario": function,
                "priority": str(item.get("priority", "待定")),
                "capability_gap": function,
                "capability_image": portrait,
                "deep_capability_portrait": portrait,
                "project_function": function,
                "mission_effect": military_value,
                "military_utility": military_value,
                "strike_countermeasure_value": mechanism,
                "novelty": mechanism,
                "foresight": development_path,
                "operational_mechanism": mechanism,
                "development_path": development_path,
                "risk_boundaries": [failure_boundary] if failure_boundary else [],
                "operational_constraints": [failure_boundary] if failure_boundary else [],
                "evidence_ids": evidence_ids,
                "evidence_basis": [f"直接证据：{value}" for value in evidence_ids],
                "agent_contributions": ["S1–S5 完成机理、对抗、工程与证据补强", "S6 完成组合评审与装备画像综合"],
                "reasoning_refs": [f"S6 / {hypothesis_id or capability_id}"],
                "confidence": float(item.get("confidence") or item.get("expert_score") or 0),
                "verification_status": str(item.get("verification_status", "assessed")),
                "confidence_limited": bool(item.get("confidence_limited", False)),
                "selection_quality_status": str(item.get("selection_quality_status", "expert_assessed")),
                "provenance_status": "s6_provisional",
            }
        )
    return rows


def _remove_raw_query_from_portrait_lede(value: object, *, scenario: object = "") -> str:
    """Keep a combat-scene lede, never echo a research Query as that scene."""

    portrait = str(value or "").strip()
    if not portrait:
        return portrait
    raw_scenario = str(scenario or "").strip()
    scenario_is_research_instruction = bool(
        raw_scenario
        and any(
            marker in raw_scenario
            for marker in (
                "深度研究",
                "研究任务",
                "长期记忆",
                "装备研究",
                "发展需求",
            )
        )
    )
    if scenario_is_research_instruction:
        portrait = portrait.replace(raw_scenario, "任务相关作战阶段")
    if raw_scenario and raw_scenario in portrait:
        portrait = portrait.replace(
            f"面向{raw_scenario}，针对",
            "在任务相关作战阶段，针对",
            1,
        )
    # Legacy fallback cards sometimes use the full research instruction as the
    # value after “面向”. It is not a military scene and should not leak into
    # the user-visible capability overview.
    portrait = re.sub(
        r"(概述：?)面向(?:深度研究|理解|长期记忆|研究任务|装备研究)[^，。]{0,360}，针对",
        r"\1在任务相关作战阶段，针对",
        portrait,
        count=1,
    )
    return portrait


def _capability_labeled_value(text: str, label: str) -> str:
    marker = f"{label}："
    if marker not in text:
        return ""
    tail = text.split(marker, 1)[1]
    boundaries = [
        tail.find(f"。{next_label}：")
        for next_label in ("军事价值", "深度机制", "前瞻判断", "新颖性", "证据约束")
        if f"。{next_label}：" in tail
    ]
    end = min(boundaries) if boundaries else len(tail)
    return tail[:end].strip("。； ")


def _catalog_payload(agent_path: Path, preset_path: Path) -> dict:
    registry = AgentRegistry.load(agent_path)
    policy = load_preset_policy(preset_path)
    default_provider = os.environ.get("EQUIPMENT_DR_PROVIDER", "codex")
    responses_base_url = os.environ.get(
        "EQUIPMENT_DR_BASE_URL", "https://api.openai.com/v1/responses"
    )
    responses_api_key_env = os.environ.get(
        "EQUIPMENT_DR_API_KEY_ENV", "EQUIPMENT_DR_API_KEY"
    )
    codex_base_url = os.environ.get(
        "EQUIPMENT_DR_CODEX_BASE_URL", "https://api.openai.com/v1"
    )
    codex_api_key_env = os.environ.get(
        "EQUIPMENT_DR_CODEX_API_KEY_ENV", "EQUIPMENT_DR_CODEX_API_KEY"
    )
    route_names = {
        "new_winning_mechanism": "新制胜机理",
        "traditional_gap": "传统能力缺口",
        "war_case_learning": "局部战争案例",
    }
    return {
        "report_templates": [
            {
                "id": "project_argument_v1",
                "name": "项目论证五章模板（推荐）",
                "description": "需求分析、项目画像、总体方案、关键技术、研制基础；强化国内外案例对比、作战流程和体系贡献。",
                "default": True,
            },
            {
                "id": "three_layer_nine_item",
                "name": "三层九项模板（兼容）",
                "description": "保留需求挖掘、技术攻关、能力图像与效能贡献三层九项结构。",
                "default": False,
            },
        ],
        "execution_profiles": [
            {
                "id": "legacy_v1",
                "name": "传统固定编排",
                "short_name": "传统模式",
                "description": "采用传统固定流程执行，适合兼容回滚、稳定复现和对照研究。",
                "default": False,
                "recommended": False,
                "selectable": True,
                "badge": "兼容",
            },
            {
                "id": "optimized_v2",
                "name": "协同优化编排",
                "short_name": "协同模式",
                "description": "3–4 个业务 Agent 并行研判，随后进入 S1–S6 Cohort 与风险门控，适合普通研究任务。",
                "default": False,
                "recommended": True,
                "selectable": True,
                "badge": "推荐",
            },
            {
                "id": "swarm_quality_v1",
                "name": "质量残差蜂群",
                "short_name": "质量集群",
                "description": "保留 S1–S6 骨架，按质量残差弹性孵化最多 12 个专用 Agent，强化探索、挑战与独立收敛。",
                "default": False,
                "recommended": False,
                "selectable": True,
                "badge": "高质量",
                "evaluation_only": True,
            },
            {
                "id": "winning_swarm_dynamic_v2",
                "name": "Mission Graph 动态蜂群",
                "short_name": "动态蜂群",
                "description": "依据 Mission Graph 动态孵化 8–16 个实例，按依赖事件并行执行，适合复杂任务与最高并发研究。",
                "default": True,
                "recommended": False,
                "selectable": True,
                "badge": "最高并发",
                "evaluation_only": True,
            },
        ],
        "interaction_modes": [
            {
                "id": "expert",
                "name": "专家模式",
                "description": "由专家给定主题、边界和发现分支，Codex按显式约束细化执行。",
            },
            {
                "id": "autonomous",
                "name": "智能模式",
                "description": "Codex先执行场景发散和元编排，再动态选择主次发现分支。",
            },
        ],
        "discovery_branches": [
            {
                "id": code,
                "name": spec.name,
                "runtime_route": spec.route,
                "emphasis": list(spec.emphasis),
                "specialist_agent_ids": list(spec.specialist_agent_ids),
                "required_capability_tags": list(spec.required_capability_tags),
                "required_outputs": list(spec.required_outputs),
                "step_modes": [
                    {
                        "step": step,
                        "execution_mode": mode,
                    }
                    for step, mode in winning_step_modes(
                        code,
                        research_route=spec.route,
                    ).items()
                ],
            }
            for code, spec in BRANCH_BLUEPRINTS.items()
        ],
        "routes": [
            {
                "id": route_id,
                "name": route_names.get(route_id, route_id),
                "required_tags": required_tags,
                "optional_tags": policy.optional_capability_tags.get(route_id, []),
            }
            for route_id, required_tags in policy.required_capability_tags.items()
        ],
        "agents": [
            {
                "agent_id": agent.agent_id,
                "display_name": agent.display_name,
                "description": agent.description,
                "capability_tags": agent.capability_tags,
                "tools": agent.tools,
                "visible_sections": agent.context_policy.get("visible_sections", []),
                "skills": agent.skills,
                "skill_ids": agent.skill_ids,
                "shared_skills": agent.shared_skills,
                "knowledge_pack_ids": agent.knowledge_pack_ids,
                "knowledge_packs": agent.knowledge_packs,
                "harness_profile": agent.harness_profile,
                "harness_profile_config": (
                    {
                        "budget": registry.get_harness_profile(agent.harness_profile).budget,
                        "stop_conditions": registry.get_harness_profile(agent.harness_profile).stop_conditions,
                        "phase_tools": registry.get_harness_profile(agent.harness_profile).phase_tools,
                    }
                    if agent.harness_profile
                    else {}
                ),
                "research_policy": agent.research_policy,
                "handoff_policy": agent.handoff_policy,
            }
            for agent in registry.enabled_baseline_agents()
        ],
        "shared_skill_layer": registry.shared_skill_catalog(),
        "knowledge_packs": registry.knowledge_pack_catalog(),
        "provider": {
            "type": "multi_agent_adapter",
            "default_provider": default_provider,
            "available_providers": ["codex", "responses"],
            "provider_options": [
                {
                    "id": "codex",
                    "name": "Codex CLI 作为 Agent",
                    "description": "每个架构 Agent 使用隔离的 codex exec 会话。",
                    "default_base_url": codex_base_url,
                    "default_api_key_env": codex_api_key_env,
                    "credential_configured": bool(
                        os.environ.get(codex_api_key_env, "").strip()
                    ),
                },
                {
                    "id": "responses",
                    "name": "自定义 Agent 适配器",
                    "description": "通过 Responses-compatible API 调用自定义 Agent。",
                    "default_base_url": responses_base_url,
                    "default_api_key_env": responses_api_key_env,
                    "credential_configured": bool(
                        os.environ.get(responses_api_key_env, "").strip()
                    ),
                },
            ],
            "execution_fields": [
                "provider",
                "model",
                "base_url",
                "api_key_env",
                "agent_models",
            ],
            "codex_available": shutil.which(os.environ.get("EQUIPMENT_DR_CODEX_COMMAND", "codex")) is not None,
            "codex_command": os.environ.get("EQUIPMENT_DR_CODEX_COMMAND", "codex"),
            "model": os.environ.get("EQUIPMENT_DR_MODEL", registry.default_model),
            "default_base_url": responses_base_url,
            "default_api_key_env": responses_api_key_env,
            "default_codex_base_url": codex_base_url,
            "default_codex_api_key_env": codex_api_key_env,
            "default_mode": os.environ.get("EQUIPMENT_DR_MODE", "fake"),
            "modes": ["fake", "real"],
            "configurable_agent_ids": [
                *registry.all_agent_ids(),
            ],
            "default_agent_models": _agent_model_defaults(),
        },
    }


def _agent_model_defaults() -> dict[str, dict[str, str]]:
    raw = os.environ.get("EQUIPMENT_DR_AGENT_MODELS_JSON", "{}").strip() or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        str(agent_id): {
            key: str(item[key])
            for key in ("provider", "model", "base_url", "api_key_env")
            if key in item and str(item[key]).strip()
        }
        for agent_id, item in value.items()
        if isinstance(item, dict)
    }


def _actual_baseline_agent_ids(rows: list[dict]) -> list[str]:
    activity_types = {
        "baseline_discovery_started",
        "baseline_model_call_started",
        "baseline_analysis_started",
        "baseline_agent_completed",
    }
    plan_types = {
        "run_started",
        "baseline_pipeline_started",
        "baseline_wave_started",
    }
    actual: list[str] = []
    planned: list[str] = []
    for row in rows:
        event_type = str(row.get("event_type", ""))
        if event_type not in activity_types | plan_types:
            continue
        payload = row.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        event = payload.get("event", payload)
        event = event if isinstance(event, dict) else {}
        details = event.get("payload", event)
        details = details if isinstance(details, dict) else {}
        if event_type in activity_types:
            agent_id = str(
                event.get("actor")
                or event.get("agent_id")
                or details.get("agent_id")
                or ""
            ).strip()
            if agent_id and agent_id not in actual:
                actual.append(agent_id)
            continue
        for agent_id in details.get("agent_ids", []):
            normalized = str(agent_id).strip()
            if normalized and normalized not in planned:
                planned.append(normalized)
    return actual or planned


def _interaction_agents(agent_path: Path) -> list[dict]:
    registry = AgentRegistry.load(agent_path)
    agents = []
    for agent_id in registry.all_agent_ids():
        agent = registry.get(agent_id)
        agents.append(
            {
                "agent_id": agent.agent_id,
                "display_name": agent.display_name,
                "description": agent.description,
                "capability_tags": agent.capability_tags,
                "tools": agent.tools,
                "visible_sections": agent.context_policy.get("visible_sections", []),
                "skills": agent.skills,
                "skill_ids": agent.skill_ids,
                "shared_skills": agent.shared_skills,
                "knowledge_pack_ids": agent.knowledge_pack_ids,
                "knowledge_packs": agent.knowledge_packs,
                "harness_profile": agent.harness_profile,
                "harness_profile_config": (
                    {
                        "budget": registry.get_harness_profile(agent.harness_profile).budget,
                        "stop_conditions": registry.get_harness_profile(agent.harness_profile).stop_conditions,
                        "phase_tools": registry.get_harness_profile(agent.harness_profile).phase_tools,
                    }
                    if agent.harness_profile
                    else {}
                ),
                "system_agent": agent.system_agent,
                "output_contract": agent.output_contract,
                "research_policy": agent.research_policy,
                "handoff_policy": agent.handoff_policy,
            }
        )
    return agents


def _validated_execution(value: dict, provider: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("execution configuration must be an object")
    mode = str(value.get("mode") or provider.get("default_mode") or "fake")
    if mode not in {"fake", "real"}:
        raise ValueError("execution mode must be fake or real")
    if mode == "fake":
        return {"mode": "fake", "provider": "fake", "model": "fake"}
    implicit_responses = not value.get("provider") and any(
        key in value for key in ("base_url", "api_key_env")
    )
    provider_name = str(
        value.get("provider")
        or ("responses" if implicit_responses else provider.get("default_provider"))
        or "codex"
    )
    if provider_name not in {"codex", "responses"}:
        raise ValueError("real mode provider must be codex or responses")
    model = str(value.get("model") or provider["model"]).strip()
    if not model or len(model) > 200:
        raise ValueError("model name is required and must be at most 200 characters")
    default_base_url, default_api_key_env = _provider_credentials_defaults(
        provider, provider_name
    )
    base_url = str(value.get("base_url") or default_base_url).strip()
    api_key_env = str(value.get("api_key_env") or default_api_key_env).strip()
    _validate_endpoint_credentials(base_url, api_key_env, label="real mode model")
    provided_agent_models = value.get("agent_models", {})
    if not isinstance(provided_agent_models, dict):
        raise ValueError("agent_models must be an object")
    agent_models: dict[str, dict[str, str]] = {}
    raw_agent_models = {
        **provider.get("default_agent_models", {}),
        **provided_agent_models,
    }
    allowed_agent_ids = set(provider.get("configurable_agent_ids", []))
    for agent_id, raw_profile in raw_agent_models.items():
        if agent_id not in allowed_agent_ids:
            raise ValueError(f"unknown configurable agent id: {agent_id}")
        if not isinstance(raw_profile, dict):
            raise ValueError(f"agent model profile must be an object: {agent_id}")
        agent_provider = str(raw_profile.get("provider") or provider_name)
        if agent_provider not in {"codex", "responses"}:
            raise ValueError(f"agent provider is invalid: {agent_id}")
        agent_model = str(raw_profile.get("model") or model).strip()
        agent_default_base_url, agent_default_api_key_env = (
            (base_url, api_key_env)
            if agent_provider == provider_name
            else _provider_credentials_defaults(provider, agent_provider)
        )
        agent_base_url = str(
            raw_profile.get("base_url") or agent_default_base_url
        ).strip()
        agent_api_key_env = str(
            raw_profile.get("api_key_env") or agent_default_api_key_env
        ).strip()
        if not agent_model or len(agent_model) > 200:
            raise ValueError(f"agent model name is invalid: {agent_id}")
        _validate_endpoint_credentials(
            agent_base_url,
            agent_api_key_env,
            label=f"agent model ({agent_id})",
        )
        agent_models[str(agent_id)] = {
            "provider": agent_provider,
            "model": agent_model,
            "base_url": agent_base_url,
            "api_key_env": agent_api_key_env,
        }
    result = {
        "mode": "real",
        "provider": provider_name,
        "model": model,
    }
    result.update({"base_url": base_url, "api_key_env": api_key_env})
    if agent_models:
        result["agent_models"] = agent_models
    return result


def _provider_credentials_defaults(provider: dict, provider_name: str) -> tuple[str, str]:
    if provider_name == "codex":
        return (
            str(provider.get("default_codex_base_url") or "https://api.openai.com/v1"),
            str(provider.get("default_codex_api_key_env") or "EQUIPMENT_DR_CODEX_API_KEY"),
        )
    return (
        str(provider.get("default_base_url") or "https://api.openai.com/v1/responses"),
        str(provider.get("default_api_key_env") or "EQUIPMENT_DR_API_KEY"),
    )


def _validate_endpoint_credentials(base_url: str, api_key_env: str, *, label: str) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{label} URL must be HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            f"{label} URL must not contain credentials, query parameters, or fragments"
        )
    if not _valid_environment_name(api_key_env):
        raise ValueError(f"{label} API key environment variable name is invalid")


def _valid_environment_name(value: str) -> bool:
    return bool(value) and (value[0].isalpha() or value[0] == "_") and all(
        character.isalnum() or character == "_" for character in value
    )


def _missing_execution_credentials(execution: dict) -> list[str]:
    if execution.get("mode") != "real":
        return []
    names = {str(execution.get("api_key_env") or "").strip()}
    agent_models = execution.get("agent_models", {})
    if isinstance(agent_models, dict):
        names.update(
            str(profile.get("api_key_env") or "").strip()
            for profile in agent_models.values()
            if isinstance(profile, dict)
        )
    return sorted(
        name for name in names if name and not os.environ.get(name, "").strip()
    )


def _public_trace_interaction(event: dict) -> dict:
    # SqliteRunStore exports TraceProposal metadata around the original
    # TraceEvent. Live runtime events already provide the inner event directly.
    # Normalize both shapes so historical replay after an API restart retains
    # step numbers, agent plans and progress counters.
    nested_event = event.get("payload", {})
    if (
        isinstance(nested_event, dict)
        and nested_event.get("event_id")
        and nested_event.get("event_type") == event.get("event_type")
        and isinstance(nested_event.get("payload", {}), dict)
    ):
        event = nested_event
    event_type = str(event.get("event_type", "trace_event"))
    actor = str(event.get("actor", "orchestrator"))
    return {
        "event_id": str(event.get("event_id", "")),
        "created_at": str(event.get("created_at", "")),
        "actor": actor,
        "event_type": event_type,
        "category": _interaction_category(event_type),
        "title": _interaction_title(event_type, str(event.get("summary", ""))),
        "summary": str(event.get("summary", "")),
        "input_refs": list(event.get("input_refs", [])),
        "output_refs": list(event.get("output_refs", [])),
        "details": sanitize_runtime_payload(event.get("payload", {})),
        "source": "trace",
    }


def _public_session_interaction(event: dict) -> dict | None:
    event_type = str(event.get("event_type", ""))
    allowed = {
        "task_received",
        "tool_call",
        "tool_result",
        "evidence_assessed",
        "baseline_result",
        "savepoint",
    }
    if event_type not in allowed:
        return None
    actor = str(event.get("agent_id", "unknown"))
    safe_keys = {
        "task_id", "title", "summary", "capability_tags", "context_sections",
        "allowed_tools", "round_index", "recall_request", "tool_name", "call_id",
        "arguments", "status", "artifact_refs", "formal_evidence_allowed",
        "evidence_id", "decision", "quality_score", "reasons", "packet_id",
        "evidence_ids", "materialized_artifact_refs", "checkpoint_id", "output_refs",
        "worker_report_id",
    }
    details = {key: value for key, value in event.items() if key in safe_keys}
    tool_name = str(event.get("tool_name", ""))
    summary = str(event.get("summary", ""))
    if not summary:
        summary = tool_name or str(event.get("title", "")) or event_type
    return {
        "event_id": str(event.get("call_id") or event.get("checkpoint_id") or f"{actor}:{event_type}"),
        "created_at": str(event.get("created_at", "")),
        "actor": actor,
        "event_type": event_type,
        "category": _interaction_category(event_type),
        "title": _interaction_title(event_type, tool_name or summary),
        "summary": summary,
        "input_refs": [],
        "output_refs": list(event.get("output_refs", event.get("evidence_ids", []))),
        "details": sanitize_runtime_payload(details),
        "source": "session_projection",
    }


def _interaction_category(event_type: str) -> str:
    if event_type in {"tool_call", "tool_result", "evidence_assessed"}:
        return "tool"
    if "delegated" in event_type or event_type in {"run_started", "task_received"}:
        return "delegation"
    if (
        "reasoning" in event_type
        or "winning_stage" in event_type
        or "winning_subagent" in event_type
        or "winning_model" in event_type
        or "specialist_" in event_type
        or "swarm_" in event_type
        or "hypothesis_" in event_type
        or "winning_inner_loop" in event_type
        or "winning_middle_loop" in event_type
    ):
        return "reasoning"
    if "recall" in event_type:
        return "recall"
    if event_type == "savepoint":
        return "checkpoint"
    if "audit" in event_type:
        return "audit"
    if event_type.startswith("report_model_"):
        return "output"
    return "output"


def _interaction_title(event_type: str, fallback: str) -> str:
    labels = {
        "run_started": "研究任务启动与分解",
        "baseline_pipeline_started": "专业研究流水线启动",
        "baseline_discovery_started": "Agent 开始多源检索",
        "baseline_discovery_lane_completed": "检索通道完成",
        "baseline_discovery_completed": "Agent 多源检索完成",
        "baseline_analysis_completed": "Agent 结构化分析完成",
        "agent_task_delegated": "编排器委派任务",
        "agent_harness_completed": "差异化 Harness 执行完成",
        "task_received": "Agent 接收研究任务",
        "tool_call": "工具调用",
        "tool_result": "工具结果",
        "evidence_assessed": "证据质量评估",
        "baseline_result": "基线研究结果",
        "savepoint": "保存点",
        "baseline_agent_completed": "Agent 任务完成",
        "baseline_agents_summarized": "编排器汇总初检",
        "winning_subagent_completed": "制胜机理细化子 Agent 完成",
        "winning_model_queue_started": "S Agent 等待模型槽位",
        "winning_model_call_started": "S Agent 模型调用启动",
        "winning_model_call_progress": "S Agent 持续执行",
        "winning_model_call_completed": "S Agent 模型调用完成",
        "swarm_planned": "动态制胜 Agent 群规划",
        "specialist_recruitment_planned": "专用 Agent 招聘合同形成",
        "specialist_spawned": "专用 Agent 招聘与孵化",
        "specialist_session_started": "独立 Codex CLI 会话启动",
        "specialist_session_completed": "独立 Codex CLI 会话结束",
        "specialist_completed": "专用 Agent 业务任务完成",
        "specialist_pruned": "专用 Agent 淘汰回收",
        "winning_specialized_seed_recovered": "动态蜂群专用候选恢复",
        "winning_specialized_seed_empty": "动态蜂群专用候选生成完成",
        "hypothesis_created": "候选制胜假设进入账本",
        "hypothesis_merged": "候选贡献定向合并",
        "hypothesis_rejected": "候选制胜假设淘汰",
        "swarm_gate_evaluated": "动态 Agent 群质量门控",
        "winning_inner_loop_evaluated": "制胜机理内循环批判",
        "winning_middle_loop_evaluated": "制胜机理中循环批判",
        "winning_reasoning_step_completed": "制胜机理六步推理",
        "winning_stage_completed": "制胜机理分层门控",
        "capability_image_created": "能力画像生成",
        "report_model_queue_started": "Reporter 等待模型槽位",
        "report_model_call_started": "Reporter 模型调用启动",
        "report_model_call_progress": "Reporter 持续撰写",
        "report_model_call_completed": "Reporter 模型调用完成",
    }
    return labels.get(event_type, fallback or event_type)
