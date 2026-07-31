from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable
import hashlib
import json
import shutil
import sqlite3

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from evals.aggregate import aggregate_pairwise
from evals.cli import run_systems
from evals.config import load_eval_config
from evals.judging import judge_pair_file
from evals.models import EvalQuery, EvalRunResult, read_jsonl
from evals.pairwise import build_blind_pairs
from evals.web_api import (
    JudgeLLMConfig,
    _dataset_by_id,
    _list_datasets,
    _now,
    _require_role,
    _safe_id,
    _validate_judge_llm_config,
    _write_manifest,
)

from .reporting import build_bundle, effect_summary, write_ablation_report, write_json
from .validation import validate_variant_trace


ABLATION_VARIANTS = ("no_multisource_baseline", "no_winning_mechanism")


class AblationRunBody(BaseModel):
    experiment_id: str | None = None
    dataset_id: str = "fixture-smoke"
    query_ids: list[str] = Field(default_factory=list)
    split: str = "pilot"
    limit: int = Field(default=1, ge=1, le=132)
    mode: str = "fake"
    control_source: str = "existing"
    project_runs: dict[str, str] = Field(default_factory=dict)
    judge_mode: str = "fake"
    judge_llm: JudgeLLMConfig | None = None
    confirm_external_data: bool = False
    concurrency: int = Field(default=2, ge=1, le=4)


def create_ablation_router(
    project_root: str | Path,
    *,
    list_research_runs: Callable[[], list[dict[str, Any]]] | None = None,
    load_research_report: Callable[[str], dict[str, Any]] | None = None,
) -> APIRouter:
    root = Path(project_root).resolve()
    eval_output_root = root / "outputs" / "evals"
    output_root = eval_output_root / "ablations"
    dataset_root = eval_output_root / "datasets"
    config_path = root / "evals" / "config.yaml"
    prompt_path = root / "evals" / "pairwise_prompt_v1.md"
    router = APIRouter(prefix="/api/v1/ablations", tags=["ablations"])
    manifest_lock = Lock()
    control_lock = Lock()
    controls: dict[str, Event] = {}

    @router.get("/overview")
    def overview(x_role: str = Header(default="analyst", alias="X-Role")) -> dict[str, Any]:
        _require_role(x_role)
        return {
            "enabled": True,
            "variants": [
                {
                    "variant_id": "full_method",
                    "label": "完整方法",
                    "baseline": "multi_agent_multi_lane",
                    "winning": "S1-S6",
                    "loops": "L1-L4",
                },
                {
                    "variant_id": "no_multisource_baseline",
                    "label": "去多源基线",
                    "baseline": "single_restricted_generic_retriever",
                    "winning": "S1-S6",
                    "loops": "L1-L4",
                },
                {
                    "variant_id": "no_winning_mechanism",
                    "label": "去制胜机理",
                    "baseline": "multi_agent_multi_lane",
                    "winning": "disabled",
                    "loops": "disabled",
                },
            ],
            "datasets": _list_datasets(root, dataset_root),
            "research_runs": list_research_runs() if list_research_runs else [],
            "runs": _list_runs(output_root),
            "defaults": {
                "control_source": "existing",
                "judge_mode": "fake",
                "mode": "fake",
            },
        }

    @router.get("/datasets/{dataset_id}/queries")
    def dataset_queries(
        dataset_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        dataset = _dataset_by_id(root, dataset_root, _safe_id(dataset_id, "dataset_id"))
        queries = [EvalQuery.from_dict(row).to_dict() for row in read_jsonl(dataset["queries_path"])]
        return {"dataset_id": dataset_id, "query_count": len(queries), "queries": queries}

    @router.post("/runs", status_code=202)
    def create_run(
        body: AblationRunBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        if body.mode not in {"fake", "real"}:
            raise HTTPException(status_code=422, detail="mode 必须是 fake 或 real")
        if body.control_source not in {"existing", "rerun"}:
            raise HTTPException(status_code=422, detail="control_source 必须是 existing 或 rerun")
        if body.judge_mode not in {"fake", "real"}:
            raise HTTPException(status_code=422, detail="judge_mode 必须是 fake 或 real")
        if (body.mode == "real" or body.judge_mode == "real") and not body.confirm_external_data:
            raise HTTPException(status_code=422, detail="真实运行会发送Query和报告，必须显式确认")
        dataset = _dataset_by_id(root, dataset_root, body.dataset_id)
        all_queries = [EvalQuery.from_dict(row) for row in read_jsonl(dataset["queries_path"])]
        query_map = {item.query_id: item for item in all_queries}
        selected = list(dict.fromkeys(item.strip() for item in body.query_ids if item.strip()))
        if selected:
            unknown = sorted(set(selected) - set(query_map))
            if unknown:
                raise HTTPException(status_code=422, detail=f"未知 Query: {unknown[:5]}")
            query_ids = selected
        else:
            candidates = all_queries if body.split == "all" else [item for item in all_queries if item.split == body.split]
            query_ids = [item.query_id for item in candidates[: body.limit]]
        if not query_ids:
            raise HTTPException(status_code=422, detail="没有可运行的 Query")
        if body.judge_mode == "real" and len(query_ids) < 2:
            raise HTTPException(
                status_code=422,
                detail="真实 Judge 至少需要2条 Query；增加样本可提高结论稳定性",
            )
        injected: list[EvalRunResult] = []
        project_runs: dict[str, str] = {}
        if body.control_source == "existing":
            if load_research_report is None:
                raise HTTPException(status_code=503, detail="项目报告读取器未启用")
            available_runs = sorted(
                list_research_runs() if list_research_runs else [],
                key=lambda row: str(row.get("updated_at", "")),
                reverse=True,
            )

            def normalized_topic(value: object) -> str:
                return "".join(str(value or "").split()).rstrip("。")

            for query_id in query_ids:
                run_id = str(body.project_runs.get(query_id, "")).strip()
                if not run_id:
                    query_topic = normalized_topic(query_map[query_id].query)
                    matched = next(
                        (
                            row
                            for row in available_runs
                            if normalized_topic(row.get("topic")) == query_topic
                        ),
                        None,
                    )
                    run_id = str((matched or {}).get("run_id", "")).strip()
                if not run_id:
                    raise HTTPException(
                        status_code=422,
                        detail=f"{query_id} 未找到同主题的已完成报告，请手动选择或改用同批重跑",
                    )
                try:
                    report = load_research_report(run_id)
                except (KeyError, FileNotFoundError, ValueError) as exc:
                    raise HTTPException(status_code=422, detail=f"项目报告 {run_id} 不可用: {exc}") from exc
                injected.append(
                    EvalRunResult(
                        eval_id="pending",
                        query_id=query_id,
                        system_id="full_method",
                        status="completed",
                        answer=str(report.get("answer", "")),
                        citations=[str(item) for item in report.get("citations", [])],
                        sources=[str(item) for item in report.get("sources", [])],
                        duration_seconds=float(report.get("duration_seconds", 0) or 0),
                        usage=dict(report.get("usage", {})),
                        model_snapshot=dict(report.get("model_snapshot", {})),
                        artifact_refs=[str(item) for item in report.get("artifact_refs", [])],
                    )
                )
                project_runs[query_id] = run_id
        judge_configs = None
        if body.judge_mode == "real":
            override = _validate_judge_llm_config(
                body.judge_llm or JudgeLLMConfig(credential_source="project_env")
            )
            judge_configs = [
                {**override, "judge_id": f"{override['model']}#ablation-{index}"}
                for index in range(1, int(override["replicas"]) + 1)
            ]
        experiment_id = _safe_id(
            body.experiment_id or f"ablation-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "experiment_id",
        )
        experiment_root = output_root / experiment_id
        manifest_path = experiment_root / "manifest.json"
        if manifest_path.exists():
            raise HTTPException(status_code=409, detail="experiment_id 已存在")
        experiment_root.mkdir(parents=True, exist_ok=False)
        manifest = {
            "schema_version": "1.0",
            "experiment_id": experiment_id,
            "status": "queued",
            "stage": "queued",
            "dataset_id": body.dataset_id,
            "dataset_path": str(dataset["queries_path"]),
            "dataset_sha256": _file_sha256(Path(dataset["queries_path"])),
            "query_ids": query_ids,
            "query_count": len(query_ids),
            "control_source": body.control_source,
            "project_runs": project_runs,
            "stage_policies": {
                "full_method": {
                    "baseline": "multi_agent_multi_lane",
                    "winning_enabled": True,
                    "feedback_loops_enabled": True,
                    "meta_loop_enabled": True,
                },
                "no_multisource_baseline": {
                    "baseline": "single_restricted_generic_retriever",
                    "winning_enabled": True,
                    "feedback_loops_enabled": True,
                    "meta_loop_enabled": True,
                    "evidence_closed": True,
                },
                "no_winning_mechanism": {
                    "baseline": "multi_agent_multi_lane",
                    "winning_enabled": False,
                    "feedback_loops_enabled": False,
                    "meta_loop_enabled": False,
                },
            },
            "variants": ["full_method", *ABLATION_VARIANTS],
            "mode": body.mode,
            "judge_mode": body.judge_mode,
            "judge_prompt": {
                "path": str(prompt_path),
                "sha256": _file_sha256(prompt_path),
            },
            "eval_config": {
                "path": str(config_path),
                "sha256": _file_sha256(config_path),
            },
            "progress": {"completed": 0, "total": len(query_ids) * 3, "percent": 0},
            "created_at": _now(),
            "updated_at": _now(),
            "exploratory_only": body.control_source == "existing",
            "causal_comparison_valid": bool(
                body.control_source == "rerun"
                and body.mode == "real"
                and body.judge_mode == "real"
                and len(query_ids) >= 2
            ),
            "control_version_match": body.control_source == "rerun",
            "minimum_sample_passed": len(query_ids) >= 2,
            "error": "",
        }
        manifest["configuration_sha256"] = _configuration_sha256(manifest)
        _write_manifest(manifest_path, manifest, manifest_lock)
        cancel = Event()
        with control_lock:
            controls[experiment_id] = cancel
        thread = Thread(
            target=_execute,
            kwargs={
                "root": root,
                "output_root": output_root,
                "config_path": config_path,
                "prompt_path": prompt_path,
                "queries_path": Path(dataset["queries_path"]),
                "manifest_path": manifest_path,
                "request": body,
                "query_ids": query_ids,
                "injected_results": injected,
                "judge_configs": judge_configs,
                "manifest_lock": manifest_lock,
                "cancel": cancel,
                "on_finished": lambda: _drop_control(controls, control_lock, experiment_id),
            },
            daemon=True,
            name=f"ablation-{experiment_id}",
        )
        thread.start()
        return manifest

    @router.get("/runs/{experiment_id}")
    def run_detail(
        experiment_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        root_path = output_root / _safe_id(experiment_id, "experiment_id")
        manifest_path = root_path / "manifest.json"
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="消融实验不存在")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        live_progress = _live_progress_snapshot(root_path, payload)
        payload["live_progress"] = live_progress
        payload["progress"] = {
            "completed": live_progress["completed_tasks"],
            "total": live_progress["total_tasks"],
            "percent": live_progress["percent"],
        }
        summary_path = root_path / "summary.json"
        if summary_path.is_file():
            payload["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
        results_path = root_path / "results.jsonl"
        if results_path.is_file():
            payload["results"] = [
                {**row, "answer": str(row.get("answer", ""))[:1200], "answer_truncated": len(str(row.get("answer", ""))) > 1200}
                for row in read_jsonl(results_path)
            ]
        return payload

    @router.post("/runs/{experiment_id}/cancel", status_code=202)
    def cancel_run(
        experiment_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        safe_id = _safe_id(experiment_id, "experiment_id")
        manifest_path = output_root / safe_id / "manifest.json"
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="消融实验不存在")
        with control_lock:
            event = controls.get(safe_id)
        if event is None:
            raise HTTPException(status_code=409, detail="实验当前不在运行")
        event.set()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update({"status": "cancelling", "stage": "cancelling", "updated_at": _now()})
        _write_manifest(manifest_path, manifest, manifest_lock)
        return manifest

    @router.delete("/runs/{experiment_id}")
    def delete_run(
        experiment_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        safe_id = _safe_id(experiment_id, "experiment_id")
        run_root = output_root / safe_id
        manifest_path = run_root / "manifest.json"
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="消融实验不存在")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="运行中的实验不能删除")
        if run_root.parent.resolve() != output_root.resolve():
            raise HTTPException(status_code=422, detail="删除路径越界")
        shutil.rmtree(run_root)
        return {"experiment_id": safe_id, "deleted": True}

    @router.get("/runs/{experiment_id}/report")
    def report(
        experiment_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> PlainTextResponse:
        _require_role(x_role)
        path = output_root / _safe_id(experiment_id, "experiment_id") / "ablation-report.md"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="消融报告尚未生成")
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")

    @router.get("/runs/{experiment_id}/reports")
    def variant_reports(
        experiment_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        run_root = output_root / _safe_id(experiment_id, "experiment_id")
        results_path = run_root / "results.jsonl"
        if not (run_root / "manifest.json").is_file():
            raise HTTPException(status_code=404, detail="消融实验不存在")
        if not results_path.is_file():
            return {"experiment_id": experiment_id, "queries": []}
        _materialize_variant_reports(run_root)
        grouped: dict[str, dict[str, Any]] = {}
        for row in read_jsonl(results_path):
            query_id = str(row.get("query_id", ""))
            system_id = str(row.get("system_id", ""))
            grouped.setdefault(query_id, {})[system_id] = {
                "system_id": system_id,
                "status": str(row.get("status", "")),
                "answer": str(row.get("answer", "")),
                "citations": [str(item) for item in row.get("citations", [])],
                "duration_seconds": float(row.get("duration_seconds", 0) or 0),
                "usage": dict(row.get("usage", {})),
                "estimated_cost": float(row.get("estimated_cost", 0) or 0),
                "error": str(row.get("error", ""))[:5000],
                "saved_report": str(
                    run_root / "reports" / query_id / system_id / "report.md"
                ),
            }
        return {
            "experiment_id": experiment_id,
            "queries": [
                {"query_id": query_id, "reports": reports}
                for query_id, reports in sorted(grouped.items())
            ],
        }

    @router.get("/runs/{experiment_id}/bundle")
    def bundle(
        experiment_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> FileResponse:
        _require_role(x_role)
        run_root = output_root / _safe_id(experiment_id, "experiment_id")
        if not (run_root / "manifest.json").is_file():
            raise HTTPException(status_code=404, detail="消融实验不存在")
        path = build_bundle(run_root)
        return FileResponse(path, filename=f"{experiment_id}-ablation.zip")

    return router


def _execute(
    *,
    root: Path,
    output_root: Path,
    config_path: Path,
    prompt_path: Path,
    queries_path: Path,
    manifest_path: Path,
    request: AblationRunBody,
    query_ids: list[str],
    injected_results: list[EvalRunResult],
    judge_configs: list[dict[str, Any]] | None,
    manifest_lock: Lock,
    cancel: Event,
    on_finished: Callable[[], None],
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    experiment_id = str(manifest["experiment_id"])
    experiment_root = output_root / experiment_id
    systems = list(ABLATION_VARIANTS)
    if request.control_source == "rerun":
        systems.insert(0, "full_method")
    manifest.update({"status": "running", "stage": "running_variants", "started_at": _now(), "updated_at": _now()})
    _write_manifest(manifest_path, manifest, manifest_lock)

    def progress(completed: int, total: int) -> None:
        manifest.update(
            {
                "stage": "running_variants",
                "progress": {"completed": completed, "total": total, "percent": round(completed / max(1, total) * 100, 1)},
                "updated_at": _now(),
            }
        )
        _write_manifest(manifest_path, manifest, manifest_lock)

    try:
        for item in injected_results:
            item.eval_id = experiment_id
        config = load_eval_config(config_path, project_root=root)
        run_result = run_systems(
            project_root=root,
            queries_path=queries_path,
            eval_id=experiment_id,
            systems=systems,
            split=request.split,
            output_root=output_root,
            limit=request.limit,
            fake=request.mode == "fake",
            resume=False,
            config=config,
            query_ids=query_ids,
            max_workers=request.concurrency,
            injected_results=injected_results,
            progress_callback=progress,
            cancel_requested=cancel.is_set,
        )
        manifest["run_result"] = run_result
        _materialize_variant_reports(experiment_root)
        manifest.update({"stage": "validating_variants", "updated_at": _now()})
        _write_manifest(manifest_path, manifest, manifest_lock)
        results_path = experiment_root / "results.jsonl"
        results = [EvalRunResult.from_dict(row) for row in read_jsonl(results_path)]
        validity: dict[str, Any] = {}
        for variant in ABLATION_VARIANTS:
            rows = [item for item in results if item.system_id == variant and item.status == "completed"]
            checks = [
                validate_variant_trace(
                    variant,
                    item.artifact_refs,
                    experiment_root / "systems" / variant / item.query_id,
                )
                for item in rows
            ]
            validity[variant] = {
                "valid": bool(rows) and all(item.get("valid") for item in checks),
                "reason": "；".join(item.get("reason", "") for item in checks if item.get("reason")),
                "query_checks": checks,
            }
        manifest["validity"] = validity
        comparisons: dict[str, Any] = {}
        effects: dict[str, Any] = {}
        for variant in ABLATION_VARIANTS:
            if cancel.is_set() or not validity[variant]["valid"]:
                continue
            manifest.update(
                {
                    "stage": "building_pairs",
                    "current_comparison": variant,
                    "updated_at": _now(),
                }
            )
            _write_manifest(manifest_path, manifest, manifest_lock)
            pair_root = experiment_root / "pairs" / variant
            pair = build_blind_pairs(
                [EvalQuery.from_dict(row) for row in read_jsonl(queries_path)],
                results,
                pair_root,
                left_system="full_method",
                right_system=variant,
            )
            if not pair["pair_count"]:
                continue
            judgments = experiment_root / f"judgments.{variant}.jsonl"
            manifest.update({"stage": "judging", "updated_at": _now()})
            _write_manifest(manifest_path, manifest, manifest_lock)
            judge_pair_file(
                pair_root / "pairs.public.jsonl",
                prompt_path,
                judgments,
                judge_models=["fake-judge-a", "fake-judge-b"] if request.judge_mode == "fake" else None,
                judge_configs=judge_configs if request.judge_mode == "real" else None,
                fake=request.judge_mode == "fake",
                cancel_requested=cancel.is_set,
            )
            manifest.update({"stage": "aggregating", "updated_at": _now()})
            _write_manifest(manifest_path, manifest, manifest_lock)
            comparison = aggregate_pairwise(
                judgments,
                pair_root / "pairs.admin.jsonl",
                results_path,
                bootstrap_samples=500,
            )
            comparisons[variant] = comparison
            effects[variant] = effect_summary(comparison, variant)
        snapshots = {
            json.dumps(item.model_snapshot, ensure_ascii=False, sort_keys=True)
            for item in results
            if item.status == "completed"
        }
        manifest["model_snapshots"] = [
            _redact_sensitive_mapping(json.loads(item)) for item in sorted(snapshots)
        ]
        manifest["control_version_match"] = len(snapshots) <= 1
        manifest["minimum_sample_passed"] = len(query_ids) >= 2
        manifest["causal_comparison_valid"] = bool(
            request.control_source == "rerun"
            and request.mode == "real"
            and request.judge_mode == "real"
            and manifest["control_version_match"]
            and manifest["minimum_sample_passed"]
        )
        manifest["exploratory_only"] = not manifest["causal_comparison_valid"]
        summary = {
            "schema_version": "1.0",
            "experiment_id": experiment_id,
            "comparisons": comparisons,
            "effects": effects,
            "validity": validity,
            "exploratory_only": manifest["exploratory_only"],
            "causal_comparison_valid": manifest["causal_comparison_valid"],
        }
        manifest.update({"stage": "writing_report", "updated_at": _now()})
        _write_manifest(manifest_path, manifest, manifest_lock)
        write_json(experiment_root / "summary.json", summary)
        write_ablation_report(experiment_root, manifest=manifest, summary=summary)
        if cancel.is_set():
            manifest.update({"status": "cancelled", "stage": "cancelled"})
        else:
            manifest.update(
                {
                    "status": "completed" if len(comparisons) == len(ABLATION_VARIANTS) else "completed_with_failures",
                    "stage": "completed",
                    "progress": {"completed": 1, "total": 1, "percent": 100},
                }
            )
        manifest["completed_at"] = _now()
    except Exception as exc:
        secrets = [str(row.get("api_key") or "") for row in (judge_configs or [])]
        error = str(exc)
        for secret in secrets:
            if secret:
                error = error.replace(secret, "[REDACTED]")
        manifest.update({"status": "failed", "stage": "failed", "error": error[:5000], "completed_at": _now()})
    finally:
        manifest["updated_at"] = _now()
        _write_manifest(manifest_path, manifest, manifest_lock)
        on_finished()


def _list_runs(output_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not output_root.is_dir():
        return rows
    for path in output_root.iterdir():
        manifest = path / "manifest.json"
        if manifest.is_file():
            row = json.loads(manifest.read_text(encoding="utf-8"))
            if row.get("status") in {"queued", "running", "cancelling"}:
                row["live_progress"] = _live_progress_snapshot(path, row)
            rows.append(row)
    return sorted(rows, key=lambda row: str(row.get("created_at", "")), reverse=True)


def _drop_control(controls: dict[str, Event], lock: Lock, experiment_id: str) -> None:
    with lock:
        controls.pop(experiment_id, None)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configuration_sha256(manifest: dict[str, Any]) -> str:
    payload = {
        key: manifest.get(key)
        for key in (
            "dataset_id",
            "dataset_sha256",
            "query_ids",
            "control_source",
            "project_runs",
            "stage_policies",
            "variants",
            "mode",
            "judge_mode",
            "judge_prompt",
            "eval_config",
        )
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _redact_sensitive_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(marker in key.lower() for marker in ("api_key", "token", "secret", "password"))
            else _redact_sensitive_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_mapping(item) for item in value]
    return value


_GLOBAL_STAGE_LABELS = {
    "queued": "等待调度",
    "running_variants": "运行三组实验",
    "validating_variants": "检查消融有效性",
    "building_pairs": "生成匿名正反序配对",
    "judging": "双 Judge 评审",
    "aggregating": "汇总统计与置信区间",
    "writing_report": "生成消融报告与归档",
    "cancelling": "正在停止实验",
    "cancelled": "实验已停止",
    "completed": "实验已完成",
    "failed": "实验执行失败",
}


def _live_progress_snapshot(experiment_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    query_ids = [str(item) for item in manifest.get("query_ids", [])]
    variants = [str(item) for item in manifest.get("variants", [])]
    result_rows = read_jsonl(experiment_root / "results.jsonl") if (experiment_root / "results.jsonl").is_file() else []
    result_map = {
        (str(row.get("system_id")), str(row.get("query_id"))): row
        for row in result_rows
    }
    tasks: list[dict[str, Any]] = []
    progress_values: list[float] = []
    for variant in variants:
        for query_id in query_ids:
            result = result_map.get((variant, query_id))
            if result is not None:
                status = "completed" if result.get("status") == "completed" else "failed"
                tasks.append(
                    {
                        "system_id": variant,
                        "query_id": query_id,
                        "status": status,
                        "phase": "completed" if status == "completed" else "failed",
                        "phase_label": "报告已完成" if status == "completed" else "运行失败",
                        "detail": str(result.get("error") or "产物已写入，等待统一评审"),
                        "event_type": "",
                        "actor": "",
                        "updated_at": "",
                        "phase_index": 8,
                        "phase_total": 8,
                    }
                )
                progress_values.append(1.0)
                continue
            event = _latest_runtime_event(experiment_root, variant, query_id)
            phase = _phase_from_event(variant, event)
            tasks.append(
                {
                    "system_id": variant,
                    "query_id": query_id,
                    "status": "running" if event else "waiting",
                    **phase,
                }
            )
            progress_values.append(float(phase["fraction"]))
    completed_tasks = sum(item["status"] == "completed" for item in tasks)
    active_tasks = [item for item in tasks if item["status"] == "running"]
    manifest_stage = str(manifest.get("stage", "queued"))
    if active_tasks:
        current = max(active_tasks, key=lambda item: (item.get("updated_at", ""), item.get("fraction", 0)))
        current_stage_label = str(current["phase_label"])
        current_detail = f"{_variant_label(current['system_id'])} · {current['query_id']} · {current['detail']}"
    else:
        current_stage_label = _GLOBAL_STAGE_LABELS.get(manifest_stage, manifest_stage)
        comparison = str(manifest.get("current_comparison", ""))
        current_detail = (
            f"完整方法 vs {_variant_label(comparison)}"
            if comparison and manifest_stage in {"building_pairs", "judging", "aggregating"}
            else current_stage_label
        )
    if manifest_stage in {"validating_variants", "building_pairs", "judging", "aggregating", "writing_report", "completed"}:
        stage_floor = {
            "validating_variants": 72.0,
            "building_pairs": 78.0,
            "judging": 84.0,
            "aggregating": 94.0,
            "writing_report": 97.0,
            "completed": 100.0,
        }[manifest_stage]
    else:
        stage_floor = 0.0
    task_percent = round(sum(progress_values) / max(1, len(progress_values)) * 70, 1)
    percent = max(task_percent, stage_floor)
    return {
        "current_stage": manifest_stage,
        "current_stage_label": current_stage_label,
        "current_detail": current_detail,
        "completed_tasks": completed_tasks,
        "total_tasks": len(tasks),
        "percent": percent,
        "tasks": tasks,
        "updated_at": max((str(item.get("updated_at", "")) for item in tasks), default=""),
    }


def _latest_runtime_event(experiment_root: Path, variant: str, query_id: str) -> dict[str, Any] | None:
    task_root = experiment_root / "systems" / variant / query_id
    databases = sorted(task_root.glob("runtime/*/run.db"))
    if not databases:
        return None
    database = databases[-1]
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=0.1)
        try:
            row = connection.execute(
                "SELECT event_type, actor, payload_json, created_at "
                "FROM trace_events ORDER BY run_sequence DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return None
    if row is None:
        return None
    try:
        payload = json.loads(str(row[2]))
    except json.JSONDecodeError:
        payload = {}
    return {
        "event_type": str(row[0]),
        "actor": str(row[1]),
        "summary": str(payload.get("summary") or row[0]),
        "payload": payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {},
        "created_at": str(row[3]),
    }


def _phase_from_event(variant: str, event: dict[str, Any] | None) -> dict[str, Any]:
    if event is None:
        return {
            "phase": "waiting",
            "phase_label": "等待运行槽位",
            "detail": "尚未创建运行事件",
            "event_type": "",
            "actor": "",
            "updated_at": "",
            "phase_index": 0,
            "phase_total": 8,
            "fraction": 0.0,
        }
    event_type = str(event.get("event_type", ""))
    actor = str(event.get("actor", ""))
    payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
    summary = str(event.get("summary", event_type))
    if event_type in {"run_started", "discovery_blueprint_created", "discovery_meta_loop_evaluated"}:
        phase, label, index, fraction = "planning", "分析 Query 与生成蓝图", 1, 0.08
    elif event_type.startswith("baseline_") or event_type in {"agent_model_call_completed", "stop_policy_evaluated"}:
        phase, label, index, fraction = "baseline", "基线检索与证据整理", 2, 0.30
    elif event_type == "packet_admission_evaluated":
        if variant == "no_winning_mechanism":
            phase, label, index, fraction = "baseline_admission", "基线准入与报告准备", 3, 0.54
        else:
            phase, label, index, fraction = "baseline_admission", "基线准入，准备 S1–S6", 3, 0.46
    elif event_type in {"baseline_agents_summarized", "discovery_convergence_completed", "military_value_handoff_created"}:
        phase, label, index, fraction = "convergence", "基线结论汇聚", 4, 0.56
    elif event_type in {"winning_input_prepared", "winning_resources_projected", "winning_stage_completed", "winning_reasoning_step_completed"}:
        step = int(payload.get("step", payload.get("stage", 0)) or 0)
        step = max(1, min(step or 1, 6))
        phase, label, index, fraction = "winning", f"S{step} 制胜机理推演", 4 + step, 0.56 + step * 0.045
    elif event_type == "capability_image_created":
        phase, label, index, fraction = "capability", "能力画像综合", 7, 0.88
    elif event_type in {"audit_completed", "report_quality_gate_evaluated"}:
        phase, label, index, fraction = "quality", "有效性与报告质量检查", 7, 0.93
    elif event_type in {"report_model_started", "report_model_completed", "report_completed"}:
        phase, label, index, fraction = "reporting", "Reporter 生成实验报告", 8, 0.98
    else:
        phase, label, index, fraction = "running", "实验组处理中", 2, 0.22
    return {
        "phase": phase,
        "phase_label": label,
        "detail": summary,
        "event_type": event_type,
        "actor": actor,
        "updated_at": str(event.get("created_at", "")),
        "phase_index": index,
        "phase_total": 8,
        "fraction": fraction,
    }


def _variant_label(variant: str) -> str:
    return {
        "full_method": "完整方法",
        "no_multisource_baseline": "去多源基线",
        "no_winning_mechanism": "去制胜机理",
    }.get(variant, variant)


def _materialize_variant_reports(experiment_root: Path) -> None:
    results_path = experiment_root / "results.jsonl"
    if not results_path.is_file():
        return
    for row in read_jsonl(results_path):
        query_id = str(row.get("query_id", "")).strip()
        system_id = str(row.get("system_id", "")).strip()
        if not query_id or not system_id:
            continue
        target = experiment_root / "reports" / query_id / system_id
        target.mkdir(parents=True, exist_ok=True)
        answer = str(row.get("answer", ""))
        if answer:
            (target / "report.md").write_text(answer, encoding="utf-8")
        write_json(
            target / "metadata.json",
            {
                "query_id": query_id,
                "system_id": system_id,
                "status": str(row.get("status", "")),
                "citations": [str(item) for item in row.get("citations", [])],
                "duration_seconds": float(row.get("duration_seconds", 0) or 0),
                "usage": dict(row.get("usage", {})),
                "estimated_cost": float(row.get("estimated_cost", 0) or 0),
                "artifact_refs": [str(item) for item in row.get("artifact_refs", [])],
                "error": str(row.get("error", ""))[:5000],
            },
        )
