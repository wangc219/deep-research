"""装备研究 Durable Task Handler。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from platform_core.config import get_int_env
from platform_core.repositories.equipment_research_repository import EquipmentResearchRepository
from platform_core.repositories.project_repository import ProjectRepository
from platform_core.services.equipment_capability_scoring import enrich_capabilities_with_s5_scores
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_equipment import (
    EquipmentArtifactRef,
    EquipmentCapabilityVersion,
    EquipmentResearchRun,
)
from platform_core.storage.redis import get_async_redis_client
from platform_core.utils.datetime_utils import utc_now_naive
from platform_core.utils.logging_config import logger
from platform_core.workspace.paths import ensure_bound_user_workdir, user_workdir_host_dir
from sqlalchemy.ext.asyncio import AsyncSession

EQUIPMENT_RESEARCH_TASK_TYPE = "equipment_research"
EQUIPMENT_RESEARCH_CAPACITY_LIMIT = 8
EQUIPMENT_RESEARCH_MAX_RUNNING = min(
    max(get_int_env("EQUIPMENT_RESEARCH_MAX_RUNNING", 4), 1),
    EQUIPMENT_RESEARCH_CAPACITY_LIMIT,
)


def aggregate_model_usage(
    events: list[tuple[str, dict[str, Any]]],
    *,
    model_spec: str,
) -> dict[str, Any]:
    """把领域编排事件折叠为平台可展示的模型调用用量。"""
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    call_count = 0
    reported_call_count = 0
    elapsed_seconds = 0.0
    models: dict[str, dict[str, int]] = {}
    for event_type, envelope in events:
        event = envelope.get("event") if isinstance(envelope.get("event"), dict) else envelope
        projected_event_type = str(event.get("event_type") or "")
        if "model_call_completed" not in event_type and "model_call_completed" not in projected_event_type:
            continue
        call_count += 1
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", event.get("input_tokens", 0))) or 0)
        output_tokens = int(
            usage.get("output_tokens", usage.get("completion_tokens", event.get("output_tokens", 0))) or 0
        )
        total_tokens = int(usage.get("total_tokens", event.get("total_tokens", 0)) or 0)
        if not total_tokens and (input_tokens or output_tokens):
            total_tokens = input_tokens + output_tokens
        if usage or input_tokens or output_tokens or total_tokens:
            reported_call_count += 1
        totals["input_tokens"] += input_tokens
        totals["output_tokens"] += output_tokens
        totals["total_tokens"] += total_tokens
        try:
            elapsed_seconds += float(event.get("elapsed_seconds") or 0)
        except (TypeError, ValueError):
            pass
        call_model = str(event.get("model_spec") or event.get("model") or model_spec or "unknown")
        bucket = models.setdefault(
            call_model,
            {"call_count": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        bucket["call_count"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["total_tokens"] += total_tokens
    return {
        "schema_version": 1,
        "model_spec": model_spec,
        "call_count": call_count,
        "usage_reported_call_count": reported_call_count,
        "complete": call_count > 0 and reported_call_count == call_count,
        "total": totals,
        "models": models,
        "elapsed_seconds": round(elapsed_seconds, 3),
    }


async def _append(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    async with pg_manager.get_async_session_context() as session:
        repo = EquipmentResearchRepository(session)
        run = await repo.lock_run(run_id)
        if run is None or run.status in {"completed", "cancelled", "failed", "archived"}:
            return
        event = await repo.append_event(run_id, event_type, payload)
        run.updated_at = utc_now_naive()
    client = await get_async_redis_client()
    await client.xadd(
        f"equipment:events:{run_id}",
        {"payload": json.dumps(event.to_dict(), ensure_ascii=False)},
        maxlen=5000,
        approximate=True,
    )


async def _set_status(run_id: str, status: str, **extra: Any) -> EquipmentResearchRun | None:
    research_result = extra.pop("result", None)
    capability_images = extra.pop("capability_images", None)
    async with pg_manager.get_async_session_context() as session:
        repo = EquipmentResearchRepository(session)
        run = await repo.lock_run(run_id)
        if run is None:
            return None
        if run.status in {"completed", "cancelled", "failed", "archived"}:
            return run
        run.status = status
        if status == "completed":
            # A resumed run can carry the failure message from its previous
            # attempt.  Once the new attempt finishes successfully that error
            # is historical event data, not the current run state.
            run.error = ""
        if error := extra.get("error"):
            run.error = str(error)
        if relpath := extra.get("artifact_relpath"):
            run.artifact_relpath = str(relpath)
        if digest := extra.get("artifact_sha256"):
            run.artifact_sha256 = str(digest)
        next_payload = dict(run.payload or {})
        if isinstance(research_result, dict):
            next_payload["result"] = dict(research_result)
        if model_usage := extra.get("model_usage"):
            next_payload["model_usage"] = dict(model_usage)
        run.payload = next_payload
        run.updated_at = utc_now_naive()
        if status == "completed":
            await _persist_formal_capability_versions(session, run, capability_images or [])
            session.add(
                EquipmentArtifactRef(
                    id=f"artifact-{run_id}",
                    run_id=run_id,
                    relative_path=str(extra.get("artifact_relpath") or ""),
                    sha256=str(extra.get("artifact_sha256") or ""),
                )
            )
        event = await repo.append_event(run_id, "status_changed", {"status": status, **extra})
    client = await get_async_redis_client()
    await client.xadd(
        f"equipment:events:{run_id}",
        {"payload": json.dumps(event.to_dict(), ensure_ascii=False)},
        maxlen=5000,
        approximate=True,
    )
    return run


async def _get_status(run_id: str) -> str | None:
    """启动工作线程前重新读取状态，避免取消窗口继续启动模型。"""
    async with pg_manager.get_async_session_context() as session:
        run = await EquipmentResearchRepository(session).get_run(run_id)
        return str(run.status) if run is not None else None


def resolve_research_workdir(run: EquipmentResearchRun) -> Path:
    """按 Run 中受信任的 Project 绑定打开或恢复研究 Workdir。"""
    workdir_path = str((run.payload or {}).get("workdir_path") or "")
    if not workdir_path:
        raise RuntimeError("研究任务缺少 Project Workdir")
    directory_mode = str((run.payload or {}).get("directory_mode") or "")
    if directory_mode == "managed":
        ensure_bound_user_workdir(run.owner_uid, workdir_path)
    elif directory_mode != "linked":
        raise RuntimeError("研究任务缺少有效的 Project Workdir 模式")
    try:
        return user_workdir_host_dir(run.owner_uid, workdir_path)
    except FileNotFoundError as exc:
        if directory_mode == "linked":
            raise RuntimeError("研究任务绑定的 linked Project Workdir 不存在，请重新关联目录") from exc
        raise


def _run_domain(run: EquipmentResearchRun, *, resume: bool = False) -> dict[str, Any]:
    """在工作线程中调用既有装备研究编排器。"""
    from equipment_deep_research.application.dto import RunView
    from equipment_deep_research.application.factory import build_application_service
    from equipment_deep_research.orchestration.runner import DeepResearchRunner
    from equipment_deep_research.runtime_process_registry import task_process_scope
    from platform_core.services.equipment_model_adapter import bind_equipment_execution
    from platform_core.services.equipment_research_knowledge import PlatformResearchKnowledgeResolver

    project_root = Path(__file__).resolve().parents[4]
    if not (project_root / "configs" / "equipment_deep_research").exists():
        project_root = Path("/app")
    host_dir = resolve_research_workdir(run)
    output_root = host_dir / "outputs" / "equipment-research"
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = output_root / run.id
    effective_resume = resume and run_root.is_dir() and not run_root.is_symlink()
    sqlite_path = output_root / f"{run.id}.db"
    service = build_application_service(f"sqlite:///{sqlite_path}")
    payload = dict(run.payload or {})
    binding = bind_equipment_execution(payload)
    runner_kwargs = dict(binding["runner"])
    execution = dict(payload.get("execution") or {})
    execution.update(binding["execution"])
    payload["model_spec"] = binding["model_spec"]
    payload["execution"] = execution
    execution_profile_id = str(payload.get("execution_profile_id") or "")
    supplemental_information = str(payload.get("supplemental_information") or "")
    raw_knowledge_ids = payload.get("knowledge_ids", payload.get("knowledges"))
    if raw_knowledge_ids is None:
        knowledge_ids = None
    elif isinstance(raw_knowledge_ids, (list, tuple)):
        knowledge_ids = list(
            dict.fromkeys(
                str(value).strip()
                for value in raw_knowledge_ids
                if str(value).strip()
            )
        )
    else:
        # Persisted payloads predate the typed boundary.  Malformed scope must
        # fail closed instead of silently widening to every visible library.
        knowledge_ids = []
    raw_knowledge_enabled = payload.get("knowledge_enabled", True)
    view = RunView(
        run.id,
        run.topic,
        run.research_route,
        list(payload.get("selected_agent_ids") or []),
        int(payload.get("max_rounds") or 2),
        run.owner_uid,
        execution=execution,
        status="queued",
        analyst_confirmed=bool(payload.get("analyst_confirmed")),
        interaction_mode=str(payload.get("interaction_mode") or "expert"),
        discovery_branch=str(payload.get("discovery_branch") or "auto"),
        execution_profile_id=execution_profile_id,
        report_template_mode=str(payload.get("report_template_mode") or "three_layer_nine_item"),
        supplemental_information=supplemental_information,
        project_id=run.project_id,
        owner_uid=str(run.owner_uid),
        knowledge_enabled=(
            raw_knowledge_enabled
            if isinstance(raw_knowledge_enabled, bool)
            else False
        ),
        knowledge_ids=knowledge_ids,
    )
    if service.repository is not None:
        service.repository.save(view)
    else:
        service._runs[view.run_id] = view  # noqa: SLF001 - in-process fallback for tests

    events: list[tuple[str, dict[str, Any]]] = []

    def publish_event(event_type: str, event_payload: dict) -> None:
        events.append((event_type, dict(event_payload)))

    runner = DeepResearchRunner(
        project_root=project_root,
        output_root=output_root,
        agent_config_path=project_root / "configs/equipment_deep_research/agents.yaml",
        preset_config_path=project_root / "configs/equipment_deep_research/presets.yaml",
        provider_config_path=project_root / "configs/equipment_deep_research/providers.yaml",
        evidence_config_path=project_root / "configs/equipment_deep_research/evidence.yaml",
        event_sink=publish_event,
    )
    knowledge_tool_factory = PlatformResearchKnowledgeResolver()
    try:
        # Binding is side-effect free: retrieval only happens if an eligible
        # Agent explicitly emits query_kb during its model turn.
        research_knowledge_tools = knowledge_tool_factory(view, publish_event)
        # Every provider child process is registered against the durable
        # platform Run.  The async task boundary can then terminate the exact
        # process groups on cancel/timeout even though the legacy runner owns a
        # synchronous event loop inside this worker thread.
        with task_process_scope(run.id):
            # 平台任务把模型、地址与密钥作为本次 runner 调用的显式参数传入。
            # 不再覆盖进程级环境变量，否则环境锁会把同一 Worker 内的长时研究串行化。
            result = runner.run(
                topic=run.topic,
                supplemental_information=supplemental_information,
                research_knowledge_tools=research_knowledge_tools,
                research_route=run.research_route,
                run_id=run.id,
                agent_ids=list(payload.get("selected_agent_ids") or []) or None,
                max_rounds=int(payload.get("max_rounds") or 2),
                analyst_confirmed=view.analyst_confirmed,
                interaction_mode=view.interaction_mode,
                discovery_branch=view.discovery_branch,
                execution_profile_id=view.execution_profile_id or "legacy_v1",
                report_template_mode=view.report_template_mode,
                project_id=view.project_id,
                resume=effective_resume,
                **runner_kwargs,
            )
    finally:
        knowledge_tool_factory.close()
    relpath = f"outputs/equipment-research/{run.id}"
    digest = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    model_usage = aggregate_model_usage(events, model_spec=str(binding.get("model_spec") or ""))
    capability_images: list[dict[str, Any]] = []
    capability_path = run_root / "capability_images.json"
    if capability_path.is_file() and not capability_path.is_symlink():
        try:
            loaded_capabilities = json.loads(capability_path.read_text(encoding="utf-8"))
            if isinstance(loaded_capabilities, list):
                capability_images = [dict(item) for item in loaded_capabilities if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            logger.exception("equipment capability images could not be loaded: %s", capability_path)
    summary_path = run_root / "round_summary.json"
    if capability_images and summary_path.is_file() and not summary_path.is_symlink():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            capability_images = enrich_capabilities_with_s5_scores(
                capability_images,
                summary if isinstance(summary, dict) else {},
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            logger.exception("equipment S5 scorecards could not be loaded: %s", summary_path)
    return {
        "result": result,
        "events": events,
        "artifact_relpath": relpath,
        "artifact_sha256": digest,
        "model_usage": model_usage,
        "capability_images": capability_images,
    }


async def _run_domain_cancellable(
    run: EquipmentResearchRun,
    *,
    resume: bool,
) -> dict[str, Any]:
    """运行同步领域编排，并在取消时先回收其模型进程组。"""

    from equipment_deep_research.runtime_process_registry import (
        terminate_run_process_groups,
    )

    domain_task = asyncio.create_task(
        asyncio.to_thread(_run_domain, run, resume=resume),
        name=f"equipment-research-domain:{run.id}",
    )
    try:
        # Shield prevents cancellation from discarding the only handle to the
        # worker thread.  The handler owns explicit process cleanup below.
        return await asyncio.shield(domain_task)
    except asyncio.CancelledError:
        try:
            grace_seconds = max(
                0.0,
                min(
                    10.0,
                    float(
                        os.environ.get(
                            "EQUIPMENT_RESEARCH_CANCEL_GRACE_SECONDS",
                            "3",
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            grace_seconds = 3.0
        cleanup = await asyncio.to_thread(
            terminate_run_process_groups,
            run.id,
            grace_seconds=grace_seconds,
        )
        logger.info(
            "equipment_research cancellation cleanup: run=%s orphan=%s terminated=%s forced=%s",
            run.id,
            cleanup.orphan_count,
            cleanup.terminated_count,
            cleanup.forced_count,
        )
        # Once its provider children are gone the synchronous runner normally
        # unwinds immediately.  Await it for a bounded interval so the worker
        # slot is not released while that thread is still mutating checkpoints.
        try:
            await asyncio.wait_for(
                asyncio.shield(domain_task),
                timeout=max(5.0, grace_seconds + 5.0),
            )
        except Exception:
            if not domain_task.done():
                logger.error(
                    "equipment_research domain thread did not stop after process cleanup: run=%s",
                    run.id,
                )
        raise


async def _persist_formal_capability_versions(
    session: AsyncSession,
    run: EquipmentResearchRun,
    capability_images: list[dict[str, Any]],
) -> int:
    """Project completed S6 portraits into the platform capability ledger.

    The domain runner keeps its detailed artifacts in the bound Project
    workspace.  The Vue workbench reads PostgreSQL, so each formal S6 card
    also needs an immutable, idempotent baseline row there.
    """
    if not capability_images:
        return 0
    inserted = 0
    repo = EquipmentResearchRepository(session)
    for index, raw_snapshot in enumerate(capability_images, start=1):
        snapshot = dict(raw_snapshot)
        binding = str(
            snapshot.get("card_binding_id")
            or snapshot.get("capability_id")
            or snapshot.get("hypothesis_id")
            or index
        ).strip()
        hypothesis = str(snapshot.get("hypothesis_id") or "").strip()
        identity = f"{run.id}:{binding}:{hypothesis}"
        version_id = f"baseline-{hashlib.sha256(identity.encode()).hexdigest()[:32]}"
        if await repo.get_capability_version(version_id) is not None:
            continue
        snapshot.update(
            {
                "run_id": run.id,
                "source": "formal_s6",
                "status": "formal",
                "version_no": 1,
            }
        )
        await repo.add_capability_version(
            EquipmentCapabilityVersion(
                id=version_id,
                project_id=run.project_id,
                owner_uid=str(run.owner_uid),
                run_id=run.id,
                snapshot=snapshot,
            )
        )
        inserted += 1
    return inserted


async def run_equipment_research(context) -> dict[str, Any]:
    """执行 equipment_research Durable Task。"""
    payload = dict(context.payload or {})
    run_id = str(payload.get("run_id") or "").strip()
    action = str(payload.get("action") or "start").strip()
    if not run_id:
        raise ValueError("equipment_research payload 缺少 run_id")
    async with pg_manager.get_async_session_context() as session:
        run = await EquipmentResearchRepository(session).get_run(run_id)
        if run is not None:
            project = await ProjectRepository(session).get_for_user(run.project_id, str(run.owner_uid))
            if project is None or str(project.status) != "active":
                raise RuntimeError("研究任务绑定的 Project 不存在或已停用")
            run_payload = dict(run.payload or {})
            persisted_workdir_path = str(run_payload.get("workdir_path") or "")
            persisted_directory_mode = str(run_payload.get("directory_mode") or "")
            if persisted_workdir_path and persisted_workdir_path != str(project.workdir_path):
                raise RuntimeError("研究任务与 Project Workdir 绑定不一致")
            if persisted_directory_mode and persisted_directory_mode != str(project.directory_mode):
                raise RuntimeError("研究任务与 Project Workdir 模式不一致")
            run.payload = {
                **run_payload,
                "workdir_path": str(project.workdir_path),
                "directory_mode": str(project.directory_mode),
            }
    if run is None:
        raise RuntimeError(f"研究任务不存在: {run_id}")
    if run.status == "cancelled":
        return {"status": "cancelled"}
    run = await _set_status(run_id, "planning")
    if run is None:
        raise RuntimeError(f"研究任务不存在: {run_id}")
    if run.status != "planning":
        return {"status": run.status, "run_id": run_id}
    try:
        current_status = await _get_status(run_id)
        if current_status != "planning":
            return {"status": current_status or "missing", "run_id": run_id}
        result = await _run_domain_cancellable(run, resume=action == "resume")
        for event_type, event_payload in result.get("events") or []:
            await _append(run_id, event_type, event_payload)
        completed = await _set_status(
            run_id,
            "completed",
            result=result.get("result") or {},
            capability_images=result.get("capability_images") or [],
            artifact_relpath=result.get("artifact_relpath", ""),
            artifact_sha256=result.get("artifact_sha256", ""),
            model_usage=result.get("model_usage") or {},
        )
        return {"status": completed.status if completed is not None else "cancelled", "run_id": run_id}
    except Exception as exc:
        logger.exception("equipment_research failed: %s", run_id)
        await _set_status(run_id, "failed", error=str(exc))
        raise


async def fail_equipment_research(session, record, error: str) -> None:
    """失联或取消时把研究任务收敛为 failed。"""
    run_id = str((record.payload or {}).get("run_id") or "")
    if not run_id:
        return
    repo = EquipmentResearchRepository(session)
    run = await repo.lock_run(run_id)
    if run is None or run.status in {"completed", "cancelled", "archived"}:
        return
    run.status = "failed"
    run.error = error
    run.updated_at = utc_now_naive()
    await repo.append_event(run_id, "run_failed", {"status": "failed", "error": error})
