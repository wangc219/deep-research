from __future__ import annotations

from base64 import b64decode
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable
import json
import os
import random
import re
import shutil
from urllib.parse import urlsplit
import hashlib

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .aggregate import aggregate_pairwise
from .adapters import (
    DEFAULT_BARE_LLM_OUTPUT_TOKENS,
    DEFAULT_ZHIPU_LLM_OUTPUT_TOKENS,
    normalize_llm_base_url,
)
from .cli import run_systems
from .config import config_status, load_eval_config
from .judging import judge_pair_file
from .models import (
    PAIRWISE_V0_DIMENSIONS,
    PAIRWISE_V1_DIMENSIONS,
    EvalQuery,
    EvalRunResult,
    read_jsonl,
    write_jsonl,
)
from .pairwise import build_blind_pairs
from .query_import import import_expert_workbook
from .evolution import EvolutionRegistry, build_query_residuals
from .report_library import (
    BASELINE_REPORT_SYSTEMS,
    BaselineReportLibrary,
    query_fingerprint,
)


DEFAULT_EXPERT_WORKBOOK = Path(
    "/Users/wangchen/equipment deep research/outputs/js-equipment-benchmark-v1/"
    "expert-annotation/军事Query专家筛选标注表_300候选.xlsx"
)
ALLOWED_BENCHMARK_SYSTEMS = {
    "full_method",
    "generic_agent",
    "bare_llm",
    "zhipu_llm",
}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_JUDGE_PROMPT_CHARS = 60_000
REQUIRED_JUDGE_PROMPT_PLACEHOLDERS = (
    "{{QUERY}}",
    "{{ANSWER_A}}",
    "{{ANSWER_B}}",
    "{{PAIR_ID}}",
)


class DatasetImportBody(BaseModel):
    dataset_id: str = "expert-local-v1"
    total: int = Field(default=132, ge=1, le=300)
    pilot_count: int = Field(default=12, ge=0, le=300)
    allow_unreviewed: bool = False


class DatasetUploadBody(DatasetImportBody):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)


class BareLLMConfig(BaseModel):
    credential_source: str = "manual"
    api_protocol: str = "chat_completions"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_output_tokens: int = Field(
        default=DEFAULT_BARE_LLM_OUTPUT_TOKENS,
        ge=1,
        le=128000,
    )


class GenericAgentConfig(BaseModel):
    credential_source: str = "manual"
    auth_mode: str = "eval_api_key"
    base_url: str = ""
    api_key: str = ""
    model: str = "gpt-5.5"
    reasoning_effort: str = "high"


class ZhipuLLMConfig(BaseModel):
    credential_source: str = "eval_env"
    base_url: str = "https://yunwu.ai/v1"
    api_key: str = ""
    model: str = "glm-5.2"
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_output_tokens: int = Field(
        default=DEFAULT_ZHIPU_LLM_OUTPUT_TOKENS,
        ge=1,
        le=128000,
    )


class JudgeLLMConfig(BaseModel):
    credential_source: str = "manual"
    runtime: str = "llm_api"
    auth_mode: str = "eval_api_key"
    api_protocol: str = "responses"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_output_tokens: int = Field(default=2500, ge=256, le=32000)
    replicas: int = Field(default=2, ge=1, le=3)


class BenchmarkRunBody(BaseModel):
    eval_id: str | None = None
    dataset_id: str = "fixture-smoke"
    systems: list[str] = Field(default_factory=lambda: ["full_method", "generic_agent"])
    split: str = "pilot"
    limit: int = Field(default=1, ge=1, le=132)
    mode: str = "fake"
    judge_mode: str = "fake"
    confirm_external_data: bool = False
    resume: bool = False
    pairwise_system: str | None = None
    pairwise_systems: list[str] = Field(default_factory=list)
    generic_agent: GenericAgentConfig | None = None
    bare_llm: BareLLMConfig | None = None
    zhipu_llm: ZhipuLLMConfig | None = None
    judge_llm: JudgeLLMConfig | None = None
    judge_prompt: str | None = Field(default=None, max_length=MAX_JUDGE_PROMPT_CHARS)
    query_ids: list[str] = Field(default_factory=list)
    project_runs: dict[str, str] = Field(default_factory=dict)
    baseline_reports: dict[str, dict[str, str]] = Field(default_factory=dict)
    baseline_concurrency: int = Field(default=4, ge=1, le=8)


class BenchmarkRecordUpdateBody(BaseModel):
    display_name: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=2000)


class BenchmarkMergeBody(BaseModel):
    source_eval_ids: list[str] = Field(min_length=1, max_length=20)
    display_name: str = Field(default="", max_length=120)


class ChallengerProfileBody(BaseModel):
    profile_id: str = Field(min_length=1, max_length=64)
    base_profile_id: str = "legacy_v1"
    hypothesis: str = Field(min_length=1, max_length=2000)
    changes: dict[str, Any] = Field(default_factory=dict)


def create_benchmark_router(
    project_root: str | Path,
    *,
    list_research_runs: Callable[[], list[dict[str, Any]]] | None = None,
    load_research_report: Callable[[str], dict[str, Any]] | None = None,
) -> APIRouter:
    root = Path(project_root).resolve()
    config_path = root / "evals" / "config.yaml"
    output_root = root / "outputs" / "evals"
    dataset_root = output_root / "datasets"
    upload_root = output_root / "uploads"
    report_library = BaselineReportLibrary(output_root / "baseline-reports")
    prompt_path = root / "evals" / "pairwise_prompt_v1.md"
    default_workbook = Path(
        __import__("os").environ.get(
            "EQUIPMENT_EVAL_DEFAULT_WORKBOOK",
            str(DEFAULT_EXPERT_WORKBOOK),
        )
    ).expanduser().resolve()
    router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmarks"])
    manifest_lock = Lock()
    control_lock = Lock()
    run_controls: dict[str, Event] = {}
    evolution = EvolutionRegistry(output_root / "evolution")

    @router.get("/evolution")
    def evolution_overview(
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        return evolution.snapshot()

    @router.post("/evolution/profiles", status_code=201)
    def create_challenger_profile(
        body: ChallengerProfileBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        try:
            return evolution.create_challenger(
                profile_id=_safe_id(body.profile_id, "profile_id"),
                base_profile_id=_safe_id(body.base_profile_id, "base_profile_id"),
                hypothesis=body.hypothesis.strip(),
                changes=body.changes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/evolution/profiles/{profile_id}/approve")
    def approve_challenger_profile(
        profile_id: str,
        x_role: str = Header(default="admin", alias="X-Role"),
    ) -> dict[str, Any]:
        if x_role != "admin":
            raise HTTPException(status_code=403, detail="admin role required")
        try:
            return evolution.approve(_safe_id(profile_id, "profile_id"), actor=x_role)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/evolution/profiles/{profile_id}/activate")
    def activate_challenger_profile(
        profile_id: str,
        x_role: str = Header(default="admin", alias="X-Role"),
    ) -> dict[str, Any]:
        if x_role != "admin":
            raise HTTPException(status_code=403, detail="admin role required")
        try:
            return evolution.activate(_safe_id(profile_id, "profile_id"), actor=x_role)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/evolution/rollback")
    def rollback_champion_profile(
        x_role: str = Header(default="admin", alias="X-Role"),
    ) -> dict[str, Any]:
        if x_role != "admin":
            raise HTTPException(status_code=403, detail="admin role required")
        try:
            return evolution.rollback(actor=x_role)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/overview")
    def overview(
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        config = load_eval_config(config_path, project_root=root)
        configuration = config_status(
            config,
            selected_systems=["full_method", "generic_agent"],
        )
        project_environment = _project_environment_credentials()
        configuration["project_environment"] = {
            key: value
            for key, value in project_environment.items()
            if key != "api_key"
        }
        return {
            "configuration": configuration,
            "default_workbook": {
                "path": str(default_workbook),
                "available": default_workbook.is_file(),
                "filename": default_workbook.name,
            },
            "datasets": _list_datasets(root, dataset_root),
            "runs": _list_benchmark_runs(output_root),
            "research_runs": list_research_runs() if list_research_runs else [],
            "evolution": evolution.snapshot(),
            "supported_systems": [
                "full_method",
                "generic_agent",
                "bare_llm",
                "zhipu_llm",
            ],
            "supported_modes": ["fake", "real"],
            "judge_prompt": {
                "prompt_id": "pairwise_prompt_v1",
                "filename": prompt_path.name,
                "content": prompt_path.read_text(encoding="utf-8"),
                "required_placeholders": list(REQUIRED_JUDGE_PROMPT_PLACEHOLDERS),
                "max_chars": MAX_JUDGE_PROMPT_CHARS,
            },
        }

    @router.post("/datasets/default-import")
    def import_default_dataset(
        body: DatasetImportBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        if not default_workbook.is_file():
            raise HTTPException(status_code=404, detail="默认专家表不存在")
        return _import_xlsx_dataset(
            default_workbook,
            dataset_root,
            body,
        )

    @router.post("/datasets/upload")
    def upload_dataset(
        body: DatasetUploadBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        dataset_id = _safe_id(body.dataset_id, "dataset_id")
        filename = Path(body.filename).name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".xlsx", ".jsonl"}:
            raise HTTPException(status_code=422, detail="仅支持 .xlsx 或 .jsonl")
        try:
            payload = b64decode(body.content_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="文件内容不是有效 Base64") from exc
        if not payload or len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="上传文件为空或超过 20MB")
        target_dir = upload_root / dataset_id
        target_dir.mkdir(parents=True, exist_ok=True)
        source_path = target_dir / filename
        source_path.write_bytes(payload)
        if suffix == ".xlsx":
            result = _import_xlsx_dataset(source_path, dataset_root, body)
        else:
            result = _import_jsonl_dataset(source_path, dataset_root, body)
        result["uploaded_filename"] = filename
        return result

    @router.get("/datasets/{dataset_id}/queries")
    def dataset_queries(
        dataset_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        dataset = _dataset_by_id(root, dataset_root, _safe_id(dataset_id, "dataset_id"))
        queries = [EvalQuery.from_dict(row).to_dict() for row in read_jsonl(dataset["queries_path"])]
        return {
            "dataset_id": dataset["dataset_id"],
            "query_count": len(queries),
            "queries": queries,
        }

    @router.get("/reports")
    def baseline_reports(
        dataset_id: str | None = None,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        safe_dataset_id = _safe_id(dataset_id, "dataset_id") if dataset_id else None
        rows = report_library.list(dataset_id=safe_dataset_id)
        return {"report_count": len(rows), "reports": rows}

    @router.get("/reports/{report_id}")
    def baseline_report_detail(
        report_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        try:
            return report_library.load(_safe_id(report_id, "report_id"))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Baseline 报告不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/runs", status_code=202)
    def start_benchmark(
        body: BenchmarkRunBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        load_eval_config(config_path, project_root=root)
        requested_systems = list(dict.fromkeys(body.systems))
        reuse_project_reports = bool(body.project_runs)
        systems = [item for item in requested_systems if item != "full_method"] if reuse_project_reports else requested_systems
        unknown = sorted(set(systems) - ALLOWED_BENCHMARK_SYSTEMS)
        if unknown or not systems:
            raise HTTPException(status_code=422, detail=f"请至少选择一个可用 baseline；不支持的系统: {unknown}")
        if body.split not in {"pilot", "test", "all"}:
            raise HTTPException(status_code=422, detail="split 必须是 pilot、test 或 all")
        if body.mode not in {"fake", "real"}:
            raise HTTPException(status_code=422, detail="mode 必须是 fake 或 real")
        if body.judge_mode not in {"none", "fake", "real"}:
            raise HTTPException(status_code=422, detail="judge_mode 必须是 none、fake 或 real")
        llm_override: dict[str, Any] | None = None
        agent_override: dict[str, Any] | None = None
        zhipu_override: dict[str, Any] | None = None
        pairwise_systems = list(
            dict.fromkeys(
                [str(item).strip() for item in body.pairwise_systems if str(item).strip()]
                or ([body.pairwise_system] if body.pairwise_system else [])
            )
        )
        if not pairwise_systems:
            pairwise_systems = [
                item
                for item in ("generic_agent", "bare_llm", "zhipu_llm")
                if item in systems
            ]
        invalid_pairwise = sorted(
            item for item in pairwise_systems if item not in systems or item == "full_method"
        )
        if invalid_pairwise:
            raise HTTPException(
                status_code=422,
                detail=f"pairwise 对比对象必须是本轮已选择的 baseline: {invalid_pairwise}",
            )
        if body.judge_mode != "none" and not pairwise_systems:
            raise HTTPException(status_code=422, detail="启用评审必须选择至少一个 baseline")
        judge_configs: list[dict[str, Any]] | None = None
        judge_override: dict[str, Any] | None = None
        if body.judge_mode == "real":
            judge_override = _validate_judge_llm_config(body.judge_llm)
            judge_configs = [
                {
                    **judge_override,
                    "judge_id": f"{judge_override['model']}#expert-{index}",
                }
                for index in range(1, int(judge_override["replicas"]) + 1)
            ]
        dataset = _dataset_by_id(root, dataset_root, body.dataset_id)
        dataset_queries = [
            EvalQuery.from_dict(row) for row in read_jsonl(dataset["queries_path"])
        ]
        query_map = {item.query_id: item for item in dataset_queries}
        selected_query_ids = list(dict.fromkeys(str(item).strip() for item in body.query_ids if str(item).strip()))
        if len(selected_query_ids) > 132:
            raise HTTPException(status_code=422, detail="单次最多选择 132 条 Query")
        if selected_query_ids:
            unknown_query_ids = sorted(set(selected_query_ids) - set(query_map))
            if unknown_query_ids:
                raise HTTPException(
                    status_code=422,
                    detail=f"所选 Query 不属于当前数据集: {unknown_query_ids[:5]}",
                )
        injected_results: list[EvalRunResult] = []
        project_runs = {
            str(query_id).strip(): str(run_id).strip()
            for query_id, run_id in body.project_runs.items()
            if str(query_id).strip() and str(run_id).strip()
        }
        if reuse_project_reports:
            if load_research_report is None:
                raise HTTPException(status_code=503, detail="研究任务报告读取器未启用")
            if not selected_query_ids:
                raise HTTPException(status_code=422, detail="复用项目报告时必须手动选择 Query")
            missing_project_runs = [
                query_id for query_id in selected_query_ids if query_id not in project_runs
            ]
            if missing_project_runs:
                raise HTTPException(
                    status_code=422,
                    detail=f"以下 Query 尚未选择已完成研究任务: {missing_project_runs[:5]}",
                )
            for query_id in selected_query_ids:
                run_id = project_runs[query_id]
                try:
                    report = load_research_report(run_id)
                except (KeyError, FileNotFoundError, ValueError) as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=f"研究任务 {run_id} 的报告不可用: {exc}",
                    ) from exc
                answer = str(report.get("answer", "")).strip()
                if not answer:
                    raise HTTPException(status_code=422, detail=f"研究任务 {run_id} 没有可用报告")
                injected_results.append(
                    EvalRunResult(
                        eval_id="pending",
                        query_id=query_id,
                        system_id="full_method",
                        status="completed",
                        answer=answer,
                        citations=[str(item) for item in report.get("citations", [])],
                        sources=[str(item) for item in report.get("sources", [])],
                        evidence_context=[
                            dict(item)
                            for item in report.get("evidence_context", [])
                            if isinstance(item, dict)
                        ],
                        duration_seconds=float(report.get("duration_seconds", 0.0) or 0.0),
                        usage=dict(report.get("usage", {})),
                        model_snapshot=dict(report.get("model_snapshot", {})),
                        artifact_refs=[str(item) for item in report.get("artifact_refs", [])],
                    )
                )
        selected_baseline_reports: dict[str, dict[str, str]] = {}
        if body.baseline_reports and not selected_query_ids:
            raise HTTPException(status_code=422, detail="复用 baseline 报告时必须手动选择 Query")
        for raw_query_id, raw_system_reports in body.baseline_reports.items():
            query_id = str(raw_query_id).strip()
            if query_id not in selected_query_ids:
                raise HTTPException(
                    status_code=422,
                    detail=f"Baseline 报告对应的 Query 未被本轮选中: {query_id}",
                )
            if not isinstance(raw_system_reports, dict):
                raise HTTPException(status_code=422, detail="baseline_reports 格式无效")
            for raw_system_id, raw_report_id in raw_system_reports.items():
                system_id = str(raw_system_id).strip()
                report_id = _safe_id(str(raw_report_id).strip(), "report_id")
                if system_id not in BASELINE_REPORT_SYSTEMS or system_id not in systems:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Baseline 报告系统未被本轮选中: {system_id}",
                    )
                try:
                    saved = report_library.load(report_id)
                except (FileNotFoundError, ValueError) as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Baseline 报告 {report_id} 不可用: {exc}",
                    ) from exc
                query = query_map[query_id]
                if (
                    saved.get("dataset_id") != body.dataset_id
                    or saved.get("query_id") != query_id
                    or saved.get("system_id") != system_id
                    or saved.get("query_sha256") != query_fingerprint(query.query)
                ):
                    raise HTTPException(
                        status_code=422,
                        detail=f"Baseline 报告 {report_id} 与当前数据集、Query 或系统不匹配",
                    )
                selected_baseline_reports.setdefault(query_id, {})[system_id] = report_id
                injected_results.append(
                    report_library.as_eval_result(report_id, eval_id="pending")
                )

        if selected_query_ids:
            execution_query_ids = selected_query_ids
        else:
            execution_queries = dataset_queries
            if body.split != "all":
                execution_queries = [item for item in execution_queries if item.split == body.split]
            execution_query_ids = [item.query_id for item in execution_queries[: body.limit]]
        execution_required = {
            system_id
            for system_id in systems
            if system_id in BASELINE_REPORT_SYSTEMS
            and any(
                system_id not in selected_baseline_reports.get(query_id, {})
                for query_id in execution_query_ids
            )
        }
        if (
            (body.mode == "real" and execution_required)
            or body.judge_mode == "real"
        ) and not body.confirm_external_data:
            raise HTTPException(
                status_code=422,
                detail="真实运行或真实评审会把 Query、回答与必要上下文发送给外部模型服务，必须显式确认",
            )
        if "generic_agent" in execution_required:
            agent_override = _validate_generic_agent_config(
                body.generic_agent,
                real=body.mode == "real",
            )
        if "bare_llm" in execution_required:
            llm_override = _validate_bare_llm_config(
                body.bare_llm,
                real=body.mode == "real",
            )
        if "zhipu_llm" in execution_required:
            zhipu_override = _validate_zhipu_llm_config(
                body.zhipu_llm,
                real=body.mode == "real",
            )
        eval_id = _safe_id(
            body.eval_id or f"web-benchmark-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "eval_id",
        )
        eval_root = output_root / eval_id
        manifest_path = eval_root / "web-run.json"
        if manifest_path.is_file() and not body.resume:
            raise HTTPException(status_code=409, detail="eval_id 已存在，请更换名称或选择续跑")
        previous_manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else {}
        )
        if previous_manifest.get("status") in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="该 Benchmark 已在运行，不能重复启动")
        eval_root.mkdir(parents=True, exist_ok=True)
        prompt_snapshot_path = eval_root / "pairwise_prompt.md"
        if body.resume and body.judge_prompt is None and prompt_snapshot_path.is_file():
            judge_prompt_text = _validated_judge_prompt_text(
                prompt_snapshot_path.read_text(encoding="utf-8")
            )
            judge_prompt_source = "resumed_snapshot"
        else:
            judge_prompt_text = _validated_judge_prompt_text(
                body.judge_prompt
                if body.judge_prompt is not None
                else prompt_path.read_text(encoding="utf-8")
            )
            default_prompt_text = prompt_path.read_text(encoding="utf-8")
            judge_prompt_source = (
                "custom"
                if body.judge_prompt is not None
                and judge_prompt_text != default_prompt_text
                else "pairwise_prompt_v1"
            )
        prompt_snapshot_path.write_text(judge_prompt_text, encoding="utf-8")
        prompt_sha256 = hashlib.sha256(judge_prompt_text.encode("utf-8")).hexdigest()
        execution_query_names = [
            query_map[query_id].query
            for query_id in execution_query_ids
            if query_id in query_map
        ]
        automatic_display_name = ""
        if body.judge_mode == "none" and execution_query_names:
            automatic_display_name = f"Baseline预生成 · {execution_query_names[0]}"
            if len(execution_query_names) > 1:
                automatic_display_name += f" 等{len(execution_query_names)}条"
        manifest = {
            "schema_version": "1.4",
            "eval_id": eval_id,
            "status": "queued",
            "dataset_id": body.dataset_id,
            "dataset_path": str(dataset["queries_path"]),
            "systems": ["full_method", *systems] if reuse_project_reports else systems,
            "baseline_systems": systems,
            "project_runs": project_runs,
            "baseline_reports": selected_baseline_reports,
            "baseline_execution_required": sorted(execution_required),
            "baseline_concurrency": body.baseline_concurrency,
            "baseline_task_count": len(execution_query_ids) * len(systems),
            "full_method_source": (
                "existing_research_run"
                if reuse_project_reports
                else "benchmark_execution"
                if "full_method" in systems
                else "not_included"
            ),
            "split": "manual" if selected_query_ids else body.split,
            "limit": len(selected_query_ids) if selected_query_ids else body.limit,
            "selection_mode": "manual" if selected_query_ids else "split_limit",
            "selected_query_ids": selected_query_ids,
            "mode": body.mode,
            "judge_mode": body.judge_mode,
            "pairwise_system": pairwise_systems[0] if pairwise_systems else None,
            "pairwise_systems": pairwise_systems,
            "external_data_confirmed": body.confirm_external_data,
            "created_at": previous_manifest.get("created_at") or _now(),
            "resumed_at": _now() if previous_manifest else None,
            "updated_at": _now(),
            "error": "",
            "display_name": previous_manifest.get("display_name", "") or automatic_display_name,
            "notes": previous_manifest.get("notes", ""),
            "stage": "queued",
            "progress": {"completed": 0, "total": 0, "percent": 0},
            "judge_prompt": {
                "prompt_id": "pairwise_prompt_v1",
                "source": judge_prompt_source,
                "filename": prompt_snapshot_path.name,
                "path": str(prompt_snapshot_path),
                "sha256": prompt_sha256,
                "character_count": len(judge_prompt_text),
            },
        }
        if llm_override is not None:
            manifest["bare_llm"] = {
                "credential_source": llm_override["credential_source"],
                "api_protocol": llm_override["api_protocol"],
                "base_url_host": urlsplit(llm_override["base_url"]).hostname or "",
                "model": llm_override["model"],
                "temperature": llm_override["temperature"],
                "max_output_tokens": llm_override["max_output_tokens"],
                "api_key_present": bool(llm_override["api_key"]),
            }
        if agent_override is not None:
            manifest["generic_agent"] = {
                "credential_source": agent_override["credential_source"],
                "auth_mode": "eval_api_key",
                "base_url_host": urlsplit(agent_override["base_url"]).hostname or "",
                "model": agent_override["model"],
                "reasoning_effort": agent_override["reasoning_effort"],
                "api_key_present": bool(agent_override["api_key"]),
            }
        if zhipu_override is not None:
            manifest["zhipu_llm"] = {
                "credential_source": zhipu_override["credential_source"],
                "api_protocol": "chat_completions",
                "base_url_host": urlsplit(zhipu_override["base_url"]).hostname or "",
                "model": zhipu_override["model"],
                "temperature": zhipu_override["temperature"],
                "max_output_tokens": zhipu_override["max_output_tokens"],
                "api_key_present": bool(zhipu_override["api_key"]),
            }
        if judge_override is not None:
            manifest["judge_llm"] = {
                "credential_source": judge_override["credential_source"],
                "runtime": judge_override["runtime"],
                "auth_mode": judge_override["auth_mode"],
                "api_protocol": judge_override["api_protocol"],
                "base_url_host": urlsplit(judge_override["base_url"]).hostname or "",
                "model": judge_override["model"],
                "temperature": judge_override["temperature"],
                "max_output_tokens": judge_override["max_output_tokens"],
                "replicas": judge_override["replicas"],
                "api_key_present": bool(judge_override["api_key"]),
            }
        _write_manifest(manifest_path, manifest, manifest_lock)
        cancel_event = Event()
        with control_lock:
            run_controls[eval_id] = cancel_event
        thread = Thread(
            target=_execute_benchmark,
            kwargs={
                "root": root,
                "output_root": output_root,
                "config_path": config_path,
                "prompt_path": prompt_snapshot_path,
                "manifest_path": manifest_path,
                "queries_path": Path(dataset["queries_path"]),
                "request": body,
                "systems": systems,
                "system_overrides": {
                    key: value
                    for key, value in {
                        "generic_agent": agent_override,
                        "bare_llm": llm_override,
                        "zhipu_llm": zhipu_override,
                    }.items()
                    if value is not None
                } or None,
                "pairwise_systems": pairwise_systems,
                "judge_configs": judge_configs,
                "injected_results": injected_results,
                "report_library": report_library,
                "manifest_lock": manifest_lock,
                "cancel_event": cancel_event,
                "on_finished": lambda: _drop_run_control(run_controls, control_lock, eval_id),
            },
            daemon=True,
            name=f"benchmark-{eval_id}",
        )
        thread.start()
        return manifest

    @router.get("/runs/{eval_id}")
    def benchmark_detail(
        eval_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        safe_eval_id = _safe_id(eval_id, "eval_id")
        eval_root = output_root / safe_eval_id
        manifest_path = eval_root / "web-run.json"
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="Benchmark 运行不存在")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        results = []
        results_path = eval_root / "results.jsonl"
        if results_path.is_file():
            for row in read_jsonl(results_path):
                result = EvalRunResult.from_dict(row)
                results.append(
                    {
                        **result.to_dict(),
                        "answer": result.answer[:1200],
                        "answer_truncated": len(result.answer) > 1200,
                        "evidence_context": [],
                        "evidence_context_count": len(result.evidence_context),
                    }
                )
        summary_path = eval_root / "summary.json"
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if summary_path.is_file()
            else None
        )
        residual_path = eval_root / "query_residuals.jsonl"
        residuals = read_jsonl(residual_path) if residual_path.is_file() else []
        return {
            **manifest,
            "results": results,
            "summary": summary,
            "residuals": residuals,
        }

    @router.get("/runs/{eval_id}/results/{query_id}/{system_id}")
    def benchmark_result_detail(
        eval_id: str,
        query_id: str,
        system_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        safe_eval_id = _safe_id(eval_id, "eval_id")
        safe_query_id = _safe_id(query_id, "query_id")
        safe_system_id = _safe_id(system_id, "system_id")
        results_path = output_root / safe_eval_id / "results.jsonl"
        if not results_path.is_file():
            raise HTTPException(status_code=404, detail="Benchmark 结果不存在")
        for row in read_jsonl(results_path):
            result = EvalRunResult.from_dict(row)
            if result.query_id == safe_query_id and result.system_id == safe_system_id:
                return result.to_dict()
        raise HTTPException(status_code=404, detail="指定 Query 的系统结果不存在")

    @router.post("/runs/{eval_id}/cancel", status_code=202)
    def cancel_benchmark(
        eval_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        safe_eval_id = _safe_id(eval_id, "eval_id")
        manifest_path = output_root / safe_eval_id / "web-run.json"
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="Benchmark 运行不存在")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") not in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="该 Benchmark 当前不在运行")
        with control_lock:
            cancel_event = run_controls.get(safe_eval_id)
        if cancel_event is not None:
            cancel_event.set()
            status = "cancelling"
            stage = "cancelling"
        else:
            status = "cancelled"
            stage = "cancelled"
        manifest.update(
            {
                "status": status,
                "stage": stage,
                "cancel_requested_at": _now(),
                "updated_at": _now(),
            }
        )
        if status == "cancelled":
            manifest["completed_at"] = _now()
        _write_manifest(manifest_path, manifest, manifest_lock)
        return manifest

    @router.patch("/runs/{eval_id}")
    def update_benchmark_record(
        eval_id: str,
        body: BenchmarkRecordUpdateBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        safe_eval_id = _safe_id(eval_id, "eval_id")
        manifest_path = output_root / safe_eval_id / "web-run.json"
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="Benchmark 运行不存在")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="运行中的 Benchmark 不能编辑")
        manifest.update(
            {
                "display_name": str(body.display_name or "").strip(),
                "notes": str(body.notes or "").strip(),
                "updated_at": _now(),
            }
        )
        _write_manifest(manifest_path, manifest, manifest_lock)
        return manifest

    @router.post("/runs/{eval_id}/merge")
    def merge_benchmark_records(
        eval_id: str,
        body: BenchmarkMergeBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        target_id = _safe_id(eval_id, "eval_id")
        target_path = output_root / target_id / "web-run.json"
        if not target_path.is_file():
            raise HTTPException(status_code=404, detail="Benchmark 运行不存在")
        target = json.loads(target_path.read_text(encoding="utf-8"))
        if target.get("status") in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="运行中的 Benchmark 不能合并")

        source_ids = list(
            dict.fromkeys(
                _safe_id(str(item).strip(), "source_eval_id")
                for item in body.source_eval_ids
                if str(item).strip()
            )
        )
        if target_id in source_ids:
            raise HTTPException(status_code=422, detail="主记录不能同时作为合并来源")
        source_records: list[dict[str, Any]] = []
        source_manifests: list[tuple[Path, dict[str, Any]]] = []
        for source_id in source_ids:
            source_path = output_root / source_id / "web-run.json"
            if not source_path.is_file():
                raise HTTPException(
                    status_code=404,
                    detail=f"合并来源 Benchmark 不存在: {source_id}",
                )
            source = json.loads(source_path.read_text(encoding="utf-8"))
            if source.get("status") in {"queued", "running", "cancelling"}:
                raise HTTPException(
                    status_code=409,
                    detail=f"运行中的 Benchmark 不能合并: {source_id}",
                )
            if source.get("dataset_id") != target.get("dataset_id"):
                raise HTTPException(
                    status_code=422,
                    detail=f"合并记录必须属于同一数据集: {source_id}",
                )
            source_records.append(_merged_record_snapshot(source))
            source_manifests.append((source_path, source))

        _merge_benchmark_artifacts(
            output_root=output_root,
            target_id=target_id,
            source_ids=source_ids,
        )
        for _, source in source_manifests:
            for field in ("systems", "baseline_systems", "pairwise_systems"):
                target[field] = list(
                    dict.fromkeys(
                        [
                            *[str(item) for item in target.get(field, [])],
                            *[str(item) for item in source.get(field, [])],
                        ]
                    )
                )
            for field in ("pair_results", "judge_results"):
                merged_map = dict(source.get(field, {}))
                merged_map.update(dict(target.get(field, {})))
                target[field] = merged_map
            target["baseline_reports"] = _merge_nested_report_maps(
                dict(source.get("baseline_reports", {})),
                dict(target.get("baseline_reports", {})),
            )
        pair_results = dict(target.get("pair_results", {}))
        if pair_results:
            target["pair_result"] = {
                "pair_count": sum(
                    int(row.get("pair_count", 0) or 0)
                    for row in pair_results.values()
                    if isinstance(row, dict)
                ),
                "query_count": max(
                    (
                        int(row.get("query_count", 0) or 0)
                        for row in pair_results.values()
                        if isinstance(row, dict)
                    ),
                    default=0,
                ),
            }
        target["merged_source_records"] = source_records
        target["merged_record_ids"] = [target_id, *source_ids]
        target["merged_record_count"] = 1 + len(source_ids)
        target["merged_at"] = _now()
        target["updated_at"] = _now()
        if body.display_name.strip():
            target["display_name"] = body.display_name.strip()
        _write_manifest(target_path, target, manifest_lock)
        for source_path, source in source_manifests:
            source["merged_into"] = target_id
            source["merged_at"] = target["merged_at"]
            source["updated_at"] = _now()
            _write_manifest(source_path, source, manifest_lock)
        return target

    @router.delete("/runs/{eval_id}")
    def delete_benchmark_record(
        eval_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict[str, Any]:
        _require_role(x_role)
        safe_eval_id = _safe_id(eval_id, "eval_id")
        eval_root = output_root / safe_eval_id
        manifest_path = eval_root / "web-run.json"
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="Benchmark 运行不存在")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="运行中的 Benchmark 不能删除")
        if eval_root.parent.resolve() != output_root.resolve():
            raise HTTPException(status_code=422, detail="Benchmark 删除路径越界")
        shutil.rmtree(eval_root)
        return {"eval_id": safe_eval_id, "deleted": True}

    return router


def _benchmark_terminal_status(
    *,
    run_result: dict[str, Any],
    active_pairwise: list[str],
    pair_results: dict[str, Any],
    comparisons: dict[str, Any],
) -> str:
    """Return failure only when an output or required comparison is incomplete.

    Judge replicas are redundant attempts. Their individual transport errors remain
    in ``judge_errors`` for audit, but do not invalidate a benchmark when every
    requested comparison was still aggregated for all queries.
    """
    if int(run_result.get("failed", 0) or 0) > 0:
        return "completed_with_failures"
    for baseline in active_pairwise:
        pair_result = pair_results.get(baseline)
        comparison = comparisons.get(baseline)
        if not pair_result or not comparison:
            return "completed_with_failures"
        expected_queries = int(pair_result.get("query_count", 0) or 0)
        compared_queries = int(comparison.get("query_count", 0) or 0)
        if expected_queries <= 0 or compared_queries < expected_queries:
            return "completed_with_failures"
    return "completed"


def _execute_benchmark(
    *,
    root: Path,
    output_root: Path,
    config_path: Path,
    prompt_path: Path,
    manifest_path: Path,
    queries_path: Path,
    request: BenchmarkRunBody,
    systems: list[str],
    system_overrides: dict[str, dict[str, Any]] | None,
    pairwise_systems: list[str],
    judge_configs: list[dict[str, Any]] | None,
    injected_results: list[EvalRunResult],
    report_library: BaselineReportLibrary,
    manifest_lock: Lock,
    cancel_event: Event,
    on_finished: Callable[[], None],
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if cancel_event.is_set():
        manifest.update(
            {
                "status": "cancelled",
                "stage": "cancelled",
                "completed_at": _now(),
                "updated_at": _now(),
            }
        )
        _write_manifest(manifest_path, manifest, manifest_lock)
        on_finished()
        return
    manifest.update({"status": "running", "stage": "running_baselines", "started_at": _now(), "updated_at": _now()})
    _write_manifest(manifest_path, manifest, manifest_lock)

    def update_progress(stage: str, completed: int, total: int) -> None:
        manifest.update(
            {
                "status": "cancelling" if cancel_event.is_set() else "running",
                "stage": stage,
                "progress": {
                    "completed": int(completed),
                    "total": int(total),
                    "percent": round(int(completed) / max(1, int(total)) * 100, 1),
                },
                "updated_at": _now(),
            }
        )
        _write_manifest(manifest_path, manifest, manifest_lock)

    try:
        for item in injected_results:
            item.eval_id = str(manifest["eval_id"])
        config = load_eval_config(config_path, project_root=root)
        run_result = run_systems(
            project_root=root,
            queries_path=queries_path,
            eval_id=str(manifest["eval_id"]),
            systems=systems,
            split=request.split,
            output_root=output_root,
            limit=request.limit,
            fake=request.mode == "fake",
            resume=request.resume,
            config=config,
            system_overrides=system_overrides,
            query_ids=request.query_ids,
            max_workers=_baseline_worker_budget(
                task_count=max(1, len(request.query_ids) or request.limit) * len(systems),
                requested=request.baseline_concurrency,
            ),
            injected_results=injected_results,
            progress_callback=lambda completed, total: update_progress(
                "running_baselines", completed, total
            ),
            cancel_requested=cancel_event.is_set,
        )
        manifest["run_result"] = run_result
        eval_root = output_root / str(manifest["eval_id"])
        results_path = eval_root / "results.jsonl"
        result_rows = (
            [EvalRunResult.from_dict(row) for row in read_jsonl(results_path)]
            if results_path.is_file()
            else []
        )
        saved_reports = report_library.save_completed(
            dataset_id=str(manifest["dataset_id"]),
            queries=[EvalQuery.from_dict(row) for row in read_jsonl(queries_path)],
            results=result_rows,
            source_eval_id=str(manifest["eval_id"]),
            mode=request.mode,
        )
        manifest["saved_baseline_reports"] = [
            {
                "report_id": row["report_id"],
                "query_id": row["query_id"],
                "query": row["query"],
                "system_id": row["system_id"],
                "report_path": row["report_path"],
            }
            for row in saved_reports
        ]
        if cancel_event.is_set() or run_result.get("cancelled"):
            manifest.update(
                {
                    "status": "cancelled",
                    "stage": "cancelled",
                    "completed_at": _now(),
                    "updated_at": _now(),
                }
            )
            return
        active_pairwise = (
            [item for item in pairwise_systems if item in systems]
            if request.judge_mode != "none"
            else []
        )
        pair_results: dict[str, Any] = {}
        judge_results: dict[str, Any] = {}
        comparisons: dict[str, Any] = {}
        if active_pairwise:
            update_progress("building_pairs", 0, len(active_pairwise))
            queries = [EvalQuery.from_dict(row) for row in read_jsonl(queries_path)]
            results = [EvalRunResult.from_dict(row) for row in read_jsonl(eval_root / "results.jsonl")]
            judge_error_count = 0
            for baseline in active_pairwise:
                if cancel_event.is_set():
                    break
                pair_dir = eval_root / "pairs" / baseline
                pair_result = build_blind_pairs(
                    queries,
                    results,
                    pair_dir,
                    left_system="full_method",
                    right_system=baseline,
                )
                pair_results[baseline] = pair_result
                update_progress(
                    "building_pairs",
                    len(pair_results),
                    len(active_pairwise),
                )
                if request.judge_mode in {"fake", "real"} and pair_result["pair_count"]:
                    judgments_path = eval_root / f"judgments.{baseline}.jsonl"
                    update_progress("judging", 0, pair_result["pair_count"] * max(1, len(judge_configs or [1, 2])))
                    judge_result = judge_pair_file(
                        pair_dir / "pairs.public.jsonl",
                        prompt_path,
                        judgments_path,
                        judge_models=["fake-judge-a", "fake-judge-b"] if request.judge_mode == "fake" else None,
                        judge_configs=judge_configs if request.judge_mode == "real" else None,
                        fake=request.judge_mode == "fake",
                        progress_callback=lambda completed, total: update_progress(
                            "judging", completed, total
                        ),
                        cancel_requested=cancel_event.is_set,
                    )
                    if cancel_event.is_set() or judge_result.get("cancelled"):
                        break
                    judge_results[baseline] = judge_result
                    judge_error_count += int(judge_result["error_count"])
                    comparisons[baseline] = aggregate_pairwise(
                        judgments_path,
                        pair_dir / "pairs.admin.jsonl",
                        eval_root / "results.jsonl",
                        bootstrap_samples=500,
                    )
                    update_progress("aggregating", len(comparisons), len(active_pairwise))
            manifest["pair_results"] = pair_results
            manifest["pair_result"] = {
                "pair_count": sum(int(row["pair_count"]) for row in pair_results.values()),
                "query_count": max(
                    (int(row["query_count"]) for row in pair_results.values()),
                    default=0,
                ),
            }
            if comparisons:
                summary = {
                    "schema_version": "2.0",
                    "baseline_order": [item for item in active_pairwise if item in comparisons],
                    "comparisons": comparisons,
                }
                (eval_root / "summary.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                manifest["judge_results"] = judge_results
                manifest["judge_errors"] = judge_error_count
                profile_ids = {
                    str(item.model_snapshot.get("execution_profile_id", "legacy_v1"))
                    for item in results
                    if item.system_id == "full_method"
                }
                execution_profile_id = (
                    next(iter(profile_ids)) if len(profile_ids) == 1 else "mixed"
                )
                residuals = build_query_residuals(
                    eval_id=str(manifest["eval_id"]),
                    eval_root=eval_root,
                    queries_path=queries_path,
                    baselines=list(comparisons),
                    execution_profile_id=execution_profile_id,
                    exploratory_only=(
                        manifest.get("judge_prompt", {}).get("source") == "custom"
                        or request.split == "test"
                    ),
                )
                manifest["query_residuals"] = {
                    "path": str(eval_root / "query_residuals.jsonl"),
                    "count": len(residuals),
                    "official_count": sum(not item.exploratory_only for item in residuals),
                }
        if cancel_event.is_set():
            manifest.update(
                {
                    "status": "cancelled",
                    "stage": "cancelled",
                    "completed_at": _now(),
                    "updated_at": _now(),
                }
            )
            return
        manifest.update(
            {
                "status": _benchmark_terminal_status(
                    run_result=run_result,
                    active_pairwise=active_pairwise,
                    pair_results=pair_results,
                    comparisons=comparisons,
                ),
                "stage": "completed",
                "progress": {"completed": 1, "total": 1, "percent": 100},
                "completed_at": _now(),
                "updated_at": _now(),
            }
        )
    except Exception as exc:
        secrets = [
            str(((system_overrides or {}).get("generic_agent") or {}).get("api_key") or ""),
            str(((system_overrides or {}).get("bare_llm") or {}).get("api_key") or ""),
            str(((system_overrides or {}).get("zhipu_llm") or {}).get("api_key") or ""),
            *[str(row.get("api_key") or "") for row in (judge_configs or [])],
        ]
        error = str(exc)
        for secret in secrets:
            if secret:
                error = error.replace(secret, "[REDACTED]")
        manifest.update(
            {
                "status": "failed",
                "stage": "failed",
                "error": error[:5000],
                "completed_at": _now(),
                "updated_at": _now(),
            }
        )
    finally:
        _write_manifest(manifest_path, manifest, manifest_lock)
        on_finished()


def _drop_run_control(controls: dict[str, Event], lock: Lock, eval_id: str) -> None:
    with lock:
        controls.pop(eval_id, None)


def _baseline_worker_budget(*, task_count: int, requested: int) -> int:
    """Bound parallelism across the complete Query x baseline task matrix."""

    environment = __import__("os").environ
    env_value = environment.get("EQUIPMENT_EVAL_BASELINE_CONCURRENCY", "") or environment.get(
        "EQUIPMENT_EVAL_SYSTEM_CONCURRENCY", ""
    )
    configured = int(env_value) if env_value.isdigit() and int(env_value) > 0 else requested
    return max(1, min(int(configured), int(task_count), 8))


def _validate_generic_agent_config(
    config: GenericAgentConfig | None,
    *,
    real: bool,
) -> dict[str, Any]:
    row = config or GenericAgentConfig()
    credential_source = _credential_source(row.credential_source)
    if str(row.auth_mode or "").strip().lower() != "eval_api_key":
        raise HTTPException(status_code=422, detail="通用 Codex Agent 仅支持自定义 API URL 与 API Key")
    project_environment = _project_environment_credentials()
    base_url = str(
        project_environment["base_url"]
        if credential_source == "project_env"
        else row.base_url or ""
    ).strip()
    api_key = str(
        project_environment["api_key"]
        if credential_source == "project_env"
        else row.api_key or ""
    )
    model = str(
        row.model
        or (project_environment["model"] if credential_source == "project_env" else "")
    ).strip()
    effort = str(row.reasoning_effort or "high").strip().lower()
    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        raise HTTPException(status_code=422, detail="通用 Codex Agent 推理强度无效")
    if real and not base_url:
        raise HTTPException(status_code=422, detail="通用 Codex Agent 真实模式必须填写 API URL")
    if real and not api_key:
        raise HTTPException(status_code=422, detail="通用 Codex Agent 真实模式必须填写 API Key")
    if real and not model:
        raise HTTPException(status_code=422, detail="通用 Codex Agent 真实模式必须填写模型名称")
    try:
        normalized_url = normalize_llm_base_url(base_url) if base_url else ""
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "adapter": "codex_cli",
        "provider": "openai",
        "auth_mode": "eval_api_key",
        "credential_source": credential_source,
        "base_url": normalized_url,
        "api_key": api_key,
        "model": model or "gpt-5.5",
        "reasoning_effort": effort,
        "sandbox": "read-only",
        "web_search": {"enabled": True, "search_context_size": "medium"},
    }


def _validate_bare_llm_config(
    config: BareLLMConfig | None,
    *,
    real: bool,
) -> dict[str, Any]:
    row = config or BareLLMConfig()
    credential_source = _credential_source(row.credential_source)
    project_environment = _project_environment_credentials()
    protocol = str(row.api_protocol or "").strip().lower()
    if protocol not in {"responses", "chat_completions"}:
        raise HTTPException(status_code=422, detail="纯 LLM 协议必须是 Responses 或 Chat Completions")
    base_url = str(
        project_environment["base_url"]
        if credential_source == "project_env"
        else row.base_url or ""
    ).strip()
    model = str(
        row.model
        or (project_environment["model"] if credential_source == "project_env" else "")
    ).strip()
    api_key = str(
        project_environment["api_key"]
        if credential_source == "project_env"
        else row.api_key or ""
    )
    if real and not base_url:
        raise HTTPException(status_code=422, detail="纯 LLM 真实模式必须填写 API URL")
    if real and not api_key:
        raise HTTPException(status_code=422, detail="纯 LLM 真实模式必须填写 API Key")
    if real and not model:
        raise HTTPException(status_code=422, detail="纯 LLM 真实模式必须填写模型名称")
    try:
        normalized_url = normalize_llm_base_url(base_url) if base_url else ""
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "adapter": "compatible_llm",
        "provider": "openai",
        "credential_source": credential_source,
        "api_protocol": protocol,
        "base_url": normalized_url,
        "api_key": api_key,
        "model": model or "fake-bare-llm",
        "temperature": row.temperature,
        "max_output_tokens": row.max_output_tokens,
        "reasoning_effort": "none",
        "web_search": {"enabled": False},
    }


def _validate_zhipu_llm_config(
    config: ZhipuLLMConfig | None,
    *,
    real: bool,
) -> dict[str, Any]:
    row = config or ZhipuLLMConfig()
    credential_source = str(row.credential_source or "eval_env").strip().lower()
    if credential_source not in {"eval_env", "manual"}:
        raise HTTPException(status_code=422, detail="智谱凭据来源必须是评测环境或本次手动填写")
    base_url = str(
        os.environ.get("EQUIPMENT_EVAL_ZHIPU_BASE_URL", "")
        if credential_source == "eval_env"
        else row.base_url or ""
    ).strip()
    api_key = str(
        os.environ.get("EQUIPMENT_EVAL_ZHIPU_API_KEY", "")
        if credential_source == "eval_env"
        else row.api_key or ""
    )
    model = str(row.model or "glm-5.2").strip()
    if real and not base_url:
        raise HTTPException(status_code=422, detail="智谱 GLM 真实模式必须配置 API URL")
    if real and not api_key:
        raise HTTPException(status_code=422, detail="智谱 GLM 真实模式必须配置 API Key")
    if real and not model:
        raise HTTPException(status_code=422, detail="智谱 GLM 真实模式必须填写模型名称")
    try:
        normalized_url = normalize_llm_base_url(base_url) if base_url else ""
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "adapter": "compatible_llm",
        "provider": "zhipu",
        "credential_source": credential_source,
        "api_protocol": "chat_completions",
        "base_url": normalized_url,
        "api_key": api_key,
        "model": model or "glm-5.2",
        "temperature": row.temperature,
        "max_output_tokens": row.max_output_tokens,
        "reasoning_effort": "none",
        "web_search": {"enabled": False},
    }


def _validate_judge_llm_config(config: JudgeLLMConfig | None) -> dict[str, Any]:
    row = config or JudgeLLMConfig()
    credential_source = _credential_source(row.credential_source)
    project_environment = _project_environment_credentials()
    runtime = str(row.runtime or "").strip().lower()
    if runtime not in {"llm_api", "codex_cli"}:
        raise HTTPException(status_code=422, detail="评审运行器必须是直连 LLM API 或 Codex CLI")
    auth_mode = str(row.auth_mode or "eval_api_key").strip().lower()
    if runtime == "codex_cli" and auth_mode != "eval_api_key":
        raise HTTPException(status_code=422, detail="Codex 评审仅支持自定义 API URL 与 API Key")
    protocol = str(row.api_protocol or "").strip().lower()
    if protocol not in {"responses", "chat_completions"}:
        raise HTTPException(status_code=422, detail="评审专家协议必须是 Responses 或 Chat Completions")
    base_url = str(
        project_environment["base_url"]
        if credential_source == "project_env"
        else row.base_url or ""
    ).strip()
    api_key = str(
        project_environment["api_key"]
        if credential_source == "project_env"
        else row.api_key or ""
    )
    model = str(
        row.model
        or (project_environment["model"] if credential_source == "project_env" else "")
    ).strip()
    needs_api_credentials = True
    if needs_api_credentials and not base_url:
        raise HTTPException(status_code=422, detail="真实评审必须填写评审专家 API URL")
    if needs_api_credentials and not api_key:
        raise HTTPException(status_code=422, detail="真实评审必须填写评审专家 API Key")
    if not model:
        raise HTTPException(status_code=422, detail="真实评审必须填写评审专家模型名称")
    try:
        normalized_url = normalize_llm_base_url(base_url) if base_url else ""
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "runtime": runtime,
        "auth_mode": auth_mode,
        "credential_source": credential_source,
        "command": "codex",
        "api_protocol": protocol,
        "base_url": normalized_url,
        "api_key": api_key,
        "model": model,
        "temperature": row.temperature,
        "max_output_tokens": row.max_output_tokens,
        "replicas": row.replicas,
        "timeout_seconds": 600,
        "reasoning_effort": "high",
    }


def _credential_source(value: str) -> str:
    source = str(value or "manual").strip().lower()
    if source not in {"manual", "project_env"}:
        raise HTTPException(status_code=422, detail="凭据来源必须是项目环境或本次手动填写")
    return source


def _validated_judge_prompt_text(value: str) -> str:
    prompt = str(value or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="评审 Prompt 不能为空")
    if len(prompt) > MAX_JUDGE_PROMPT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"评审 Prompt 不能超过 {MAX_JUDGE_PROMPT_CHARS} 个字符",
        )
    missing_placeholders = [
        item for item in REQUIRED_JUDGE_PROMPT_PLACEHOLDERS if item not in prompt
    ]
    if missing_placeholders:
        raise HTTPException(
            status_code=422,
            detail=f"评审 Prompt 缺少必要占位符: {missing_placeholders}",
        )
    if '"communication_efficiency"' in prompt:
        raise HTTPException(
            status_code=422,
            detail="表达效率维度已停用，请从评审 Prompt 的 dimensions 中移除",
        )
    dimension_names = frozenset(
        name
        for name in (*PAIRWISE_V0_DIMENSIONS, *PAIRWISE_V1_DIMENSIONS)
        if f'"{name}"' in prompt
    )
    if dimension_names not in {
        PAIRWISE_V0_DIMENSIONS,
        PAIRWISE_V1_DIMENSIONS,
    }:
        raise HTTPException(
            status_code=422,
            detail="评审 Prompt 必须保留完整的 v0 或 v1 dimensions JSON 契约",
        )
    for required_key in (
        '"winner"',
        '"confidence"',
        '"dimensions"',
        '"reason"',
        '"citation_issues"',
        '"hard_failures"',
    ):
        if required_key not in prompt:
            raise HTTPException(
                status_code=422,
                detail=f"评审 Prompt 缺少输出字段: {required_key}",
            )
    return prompt + "\n"


def _project_environment_credentials() -> dict[str, Any]:
    base_url = ""
    base_url_env = ""
    for name in ("EQUIPMENT_DR_CODEX_BASE_URL", "EQUIPMENT_DR_BASE_URL"):
        candidate = str(os.environ.get(name, "")).strip()
        if not candidate:
            continue
        parsed = urlsplit(candidate)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        ):
            base_url = candidate.rstrip("/")
            base_url_env = name
            break

    configured_key_env = str(
        os.environ.get("EQUIPMENT_DR_CODEX_API_KEY_ENV")
        or os.environ.get("EQUIPMENT_DR_API_KEY_ENV")
        or ""
    ).strip()
    key_candidates = [
        configured_key_env,
        "EQUIPMENT_DR__API_KEY",
        "EQUIPMENT_DR_API_KEY",
    ]
    api_key_env = next(
        (
            name
            for name in key_candidates
            if name and str(os.environ.get(name, "")).strip()
        ),
        configured_key_env or "EQUIPMENT_DR_API_KEY",
    )
    api_key = str(os.environ.get(api_key_env, ""))
    model = str(os.environ.get("EQUIPMENT_DR_MODEL") or "gpt-5.5").strip()
    return {
        "source": "project_env",
        "base_url": base_url,
        "base_url_env": base_url_env,
        "api_key_env": api_key_env,
        "api_key": api_key,
        "api_key_present": bool(api_key),
        "model": model,
        "api_protocol": "responses",
        "ready": bool(base_url and api_key and model),
    }


def _import_xlsx_dataset(
    source_path: Path,
    dataset_root: Path,
    body: DatasetImportBody,
) -> dict[str, Any]:
    dataset_id = _safe_id(body.dataset_id, "dataset_id")
    if body.pilot_count > body.total:
        raise HTTPException(status_code=422, detail="pilot_count 不能大于 total")
    output = dataset_root / dataset_id
    try:
        manifest = import_expert_workbook(
            source_path,
            output,
            total=body.total,
            pilot_count=body.pilot_count,
            require_expert_approval=not body.allow_unreviewed,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"dataset_id": dataset_id, **manifest}


def _import_jsonl_dataset(
    source_path: Path,
    dataset_root: Path,
    body: DatasetImportBody,
) -> dict[str, Any]:
    dataset_id = _safe_id(body.dataset_id, "dataset_id")
    if body.pilot_count > body.total:
        raise HTTPException(status_code=422, detail="pilot_count 不能大于 total")
    try:
        raw_rows = read_jsonl(source_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"JSONL 解析失败: {exc}") from exc
    normalized = []
    for index, row in enumerate(raw_rows, start=1):
        query = str(row.get("query") or row.get("Query") or row.get("候选Query") or "").strip()
        if not query:
            continue
        difficulty = str(row.get("difficulty") or row.get("难度") or "medium").lower()
        if difficulty not in {"easy", "medium", "hard"}:
            difficulty = "medium"
        normalized.append(
            {
                "source_index": index,
                "query": query,
                "region": str(row.get("region") or row.get("区域") or "未标注"),
                "domain": str(row.get("domain") or row.get("领域") or "未标注"),
                "difficulty": difficulty,
            }
        )
    if len(normalized) < body.total:
        raise HTTPException(
            status_code=422,
            detail=f"JSONL 只有 {len(normalized)} 条有效 Query，少于要求的 {body.total} 条",
        )
    random.Random(20260718).shuffle(normalized)
    selected = normalized[: body.total]
    output = dataset_root / dataset_id
    output.mkdir(parents=True, exist_ok=True)
    public_rows = []
    admin_rows = []
    for index, row in enumerate(selected, start=1):
        query_id = f"Q-{index:04d}"
        public_rows.append(
            {
                "query_id": query_id,
                "query": row["query"],
                "region": row["region"],
                "domain": row["domain"],
                "difficulty": row["difficulty"],
                "split": "pilot" if index <= body.pilot_count else "test",
            }
        )
        admin_rows.append({"query_id": query_id, "source_index": row["source_index"]})
    write_jsonl(output / "queries.jsonl", public_rows)
    write_jsonl(output / "admin_mapping.jsonl", admin_rows)
    manifest = {
        "schema_version": "1.0",
        "source_workbook": str(source_path),
        "query_count": len(public_rows),
        "pilot_count": body.pilot_count,
        "test_count": len(public_rows) - body.pilot_count,
        "selection_mode": "local_jsonl_test",
        "fields": ["query_id", "query", "region", "domain", "difficulty", "split"],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {"dataset_id": dataset_id, **manifest}


def _list_datasets(root: Path, dataset_root: Path) -> list[dict[str, Any]]:
    rows = []
    fixture = root / "evals" / "fixtures" / "smoke_queries.jsonl"
    if fixture.is_file():
        rows.append(_dataset_row("fixture-smoke", fixture, {"selection_mode": "fixture"}))
    expert = root / "evals" / "data" / "expert_queries_v1"
    if (expert / "queries.jsonl").is_file():
        rows.append(_dataset_row("expert-queries-v1", expert / "queries.jsonl", _read_manifest(expert)))
    if dataset_root.is_dir():
        for path in sorted(dataset_root.iterdir()):
            if path.is_dir() and (path / "queries.jsonl").is_file():
                rows.append(_dataset_row(path.name, path / "queries.jsonl", _read_manifest(path)))
    return rows


def _dataset_row(dataset_id: str, queries_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    queries = read_jsonl(queries_path)
    return {
        "dataset_id": dataset_id,
        "query_count": len(queries),
        "pilot_count": sum(row.get("split") == "pilot" for row in queries),
        "test_count": sum(row.get("split") == "test" for row in queries),
        "selection_mode": manifest.get("selection_mode", "unknown"),
        "source_name": Path(str(manifest.get("source_workbook") or queries_path)).name,
        "queries_path": str(queries_path),
    }


def _dataset_by_id(root: Path, dataset_root: Path, dataset_id: str) -> dict[str, Any]:
    for row in _list_datasets(root, dataset_root):
        if row["dataset_id"] == dataset_id:
            return row
    raise HTTPException(status_code=404, detail="Query 数据集不存在")


def _list_benchmark_runs(output_root: Path) -> list[dict[str, Any]]:
    rows = []
    if not output_root.is_dir():
        return rows
    for path in output_root.iterdir():
        manifest_path = path / "web-run.json"
        if not path.is_dir() or not manifest_path.is_file():
            continue
        try:
            row = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(row)
    existing_ids = {str(row.get("eval_id", "")) for row in rows}
    visible_rows = [
        row
        for row in rows
        if not row.get("merged_into")
        or str(row.get("merged_into")) not in existing_ids
    ]
    return sorted(
        visible_rows,
        key=lambda row: str(row.get("created_at", "")),
        reverse=True,
    )


def _merged_record_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "eval_id": str(row.get("eval_id", "")),
        "display_name": str(row.get("display_name", "")),
        "status": str(row.get("status", "")),
        "mode": str(row.get("mode", "")),
        "judge_mode": str(row.get("judge_mode", "")),
        "limit": int(row.get("limit", 0) or 0),
        "created_at": str(row.get("created_at", "")),
        "completed_at": str(row.get("completed_at", "")),
        "record_role": (
            "baseline_preparation"
            if row.get("judge_mode") == "none"
            else "prior_evaluation"
        ),
    }


def _merge_benchmark_artifacts(
    *,
    output_root: Path,
    target_id: str,
    source_ids: list[str],
) -> None:
    target_root = output_root / target_id
    target_results_path = target_root / "results.jsonl"
    result_rows = read_jsonl(target_results_path) if target_results_path.is_file() else []
    result_keys = {
        (str(row.get("query_id", "")), str(row.get("system_id", "")))
        for row in result_rows
    }
    for source_id in source_ids:
        source_results_path = output_root / source_id / "results.jsonl"
        if not source_results_path.is_file():
            continue
        for row in read_jsonl(source_results_path):
            key = (str(row.get("query_id", "")), str(row.get("system_id", "")))
            if key in result_keys:
                continue
            result_rows.append(row)
            result_keys.add(key)
    if result_rows:
        result_rows.sort(
            key=lambda row: (str(row.get("query_id", "")), str(row.get("system_id", "")))
        )
        write_jsonl(target_results_path, result_rows)

    target_summary_path = target_root / "summary.json"
    target_summary = (
        json.loads(target_summary_path.read_text(encoding="utf-8"))
        if target_summary_path.is_file()
        else {"schema_version": "2.0", "baseline_order": [], "comparisons": {}}
    )
    target_comparisons = dict(target_summary.get("comparisons", {}))
    target_order = [str(item) for item in target_summary.get("baseline_order", [])]
    for source_id in source_ids:
        source_summary_path = output_root / source_id / "summary.json"
        if not source_summary_path.is_file():
            continue
        source_summary = json.loads(source_summary_path.read_text(encoding="utf-8"))
        for baseline in source_summary.get(
            "baseline_order", list(dict(source_summary.get("comparisons", {})))
        ):
            baseline = str(baseline)
            comparison = dict(source_summary.get("comparisons", {})).get(baseline)
            if not isinstance(comparison, dict) or baseline in target_comparisons:
                continue
            target_comparisons[baseline] = comparison
            target_order.append(baseline)
    if target_comparisons:
        target_summary.update(
            {
                "schema_version": "2.0",
                "baseline_order": list(dict.fromkeys(target_order)),
                "comparisons": target_comparisons,
            }
        )
        target_summary_path.write_text(
            json.dumps(target_summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _merge_nested_report_maps(
    source: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {
        str(query_id): {
            str(system_id): str(report_id)
            for system_id, report_id in dict(rows or {}).items()
        }
        for query_id, rows in source.items()
        if isinstance(rows, dict)
    }
    for query_id, rows in target.items():
        if not isinstance(rows, dict):
            continue
        merged.setdefault(str(query_id), {}).update(
            {
                str(system_id): str(report_id)
                for system_id, report_id in rows.items()
            }
        )
    return merged


def _read_manifest(path: Path) -> dict[str, Any]:
    target = path / "manifest.json"
    return json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}


def _write_manifest(path: Path, payload: dict[str, Any], lock: Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)


def _safe_id(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not SAFE_ID.fullmatch(text):
        raise HTTPException(status_code=422, detail=f"{field} 仅允许字母、数字、点、下划线和连字符")
    return text


def _require_role(role: str) -> None:
    if role not in {"analyst", "admin"}:
        raise HTTPException(status_code=403, detail="forbidden")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["create_benchmark_router"]
