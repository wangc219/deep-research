from pathlib import Path
import json
import shutil
import time

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from evals.models import EvalRunResult, read_jsonl, write_jsonl
from evals.web_api import (
    BareLLMConfig,
    DEFAULT_EXPERT_WORKBOOK,
    GenericAgentConfig,
    JudgeLLMConfig,
    ZhipuLLMConfig,
    _benchmark_terminal_status,
    _validate_bare_llm_config,
    _validate_generic_agent_config,
    _validate_judge_llm_config,
    _validate_zhipu_llm_config,
    create_benchmark_router,
)
from tests.evals.test_query_import import _workbook


ROOT = Path(__file__).parents[2]


def test_benchmark_terminal_status_ignores_redundant_judge_replica_errors() -> None:
    status = _benchmark_terminal_status(
        run_result={"completed": 57, "failed": 0},
        active_pairwise=["generic_agent", "bare_llm"],
        pair_results={
            "generic_agent": {"pair_count": 38, "query_count": 19},
            "bare_llm": {"pair_count": 38, "query_count": 19},
        },
        comparisons={
            "generic_agent": {"judgment_count": 72, "query_count": 19},
            "bare_llm": {"judgment_count": 76, "query_count": 19},
        },
    )

    assert status == "completed"


def test_benchmark_terminal_status_keeps_incomplete_comparison_failed() -> None:
    status = _benchmark_terminal_status(
        run_result={"completed": 57, "failed": 0},
        active_pairwise=["generic_agent"],
        pair_results={"generic_agent": {"pair_count": 38, "query_count": 19}},
        comparisons={"generic_agent": {"judgment_count": 36, "query_count": 18}},
    )

    assert status == "completed_with_failures"


def _project(tmp_path: Path) -> Path:
    (tmp_path / "evals" / "fixtures").mkdir(parents=True)
    shutil.copy(ROOT / "evals" / "config.yaml", tmp_path / "evals" / "config.yaml")
    shutil.copy(
        ROOT / "evals" / "fixtures" / "smoke_queries.jsonl",
        tmp_path / "evals" / "fixtures" / "smoke_queries.jsonl",
    )
    shutil.copy(
        ROOT / "evals" / "pairwise_prompt_v1.md",
        tmp_path / "evals" / "pairwise_prompt_v1.md",
    )
    return tmp_path


def test_benchmark_overview_exposes_project_environment_without_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project(tmp_path)
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", "PROJECT_BENCHMARK_KEY")
    monkeypatch.setenv("PROJECT_BENCHMARK_KEY", "super-secret-benchmark-key")
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "gpt-project-test")
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)

    response = client.get("/api/v1/benchmarks/overview")
    assert response.status_code == 200
    environment = response.json()["configuration"]["project_environment"]
    prompt = response.json()["judge_prompt"]
    assert prompt["filename"] == "pairwise_prompt_v1.md"
    assert "{{ANSWER_A}}" in prompt["content"]
    assert "communication_efficiency" not in prompt["content"]
    assert prompt["required_placeholders"] == [
        "{{QUERY}}",
        "{{ANSWER_A}}",
        "{{ANSWER_B}}",
        "{{PAIR_ID}}",
    ]
    assert environment == {
        "source": "project_env",
        "base_url": "https://gateway.example/v1",
        "base_url_env": "EQUIPMENT_DR_CODEX_BASE_URL",
        "api_key_env": "PROJECT_BENCHMARK_KEY",
        "api_key_present": True,
        "model": "gpt-project-test",
        "api_protocol": "responses",
        "ready": True,
    }
    assert "super-secret-benchmark-key" not in response.text


def test_benchmark_default_workbook_is_resolved_from_project_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project(tmp_path)
    monkeypatch.delenv("EQUIPMENT_EVAL_DEFAULT_WORKBOOK", raising=False)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)

    workbook = client.get("/api/v1/benchmarks/overview").json()["default_workbook"]

    assert Path(workbook["path"]) == (project / DEFAULT_EXPERT_WORKBOOK).resolve()
    assert workbook["filename"] == DEFAULT_EXPERT_WORKBOOK.name
    assert workbook["available"] is False


def test_benchmark_relative_workbook_override_is_resolved_from_project_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project(tmp_path)
    relative_workbook = Path("datasets") / "expert.xlsx"
    expected = project / relative_workbook
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"placeholder")
    monkeypatch.setenv("EQUIPMENT_EVAL_DEFAULT_WORKBOOK", str(relative_workbook))
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)

    workbook = client.get("/api/v1/benchmarks/overview").json()["default_workbook"]

    assert Path(workbook["path"]) == expected.resolve()
    assert workbook["filename"] == "expert.xlsx"
    assert workbook["available"] is True


def test_benchmark_custom_judge_prompt_is_snapshotted(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    default_prompt = client.get("/api/v1/benchmarks/overview").json()[
        "judge_prompt"
    ]["content"]
    custom_prompt = default_prompt.replace(
        "你的职责是比较最终研究成果质量",
        "本轮自定义：你的职责是比较最终研究成果质量",
        1,
    )
    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "custom-prompt-snapshot",
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent"],
            "mode": "fake",
            "judge_mode": "none",
            "judge_prompt": custom_prompt,
        },
    )
    assert started.status_code == 202, started.text
    manifest = started.json()
    assert manifest["judge_prompt"]["source"] == "custom"
    snapshot = (
        project
        / "outputs"
        / "evals"
        / "custom-prompt-snapshot"
        / "pairwise_prompt.md"
    )
    assert snapshot.read_text(encoding="utf-8") == custom_prompt.strip() + "\n"

    invalid = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "invalid-custom-prompt",
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent"],
            "mode": "fake",
            "judge_mode": "none",
            "judge_prompt": custom_prompt.replace("{{ANSWER_B}}", ""),
        },
    )
    assert invalid.status_code == 422
    assert "ANSWER_B" in invalid.text


def test_benchmark_validators_resolve_credentials_only_from_project_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", "PROJECT_BENCHMARK_KEY")
    monkeypatch.setenv("PROJECT_BENCHMARK_KEY", "server-only-secret")
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "gpt-project-test")

    configs = [
        _validate_generic_agent_config(
            GenericAgentConfig(credential_source="project_env", model=""),
            real=True,
        ),
        _validate_bare_llm_config(
            BareLLMConfig(
                credential_source="project_env",
                api_protocol="responses",
            ),
            real=True,
        ),
        _validate_judge_llm_config(
            JudgeLLMConfig(credential_source="project_env")
        ),
    ]

    for config in configs:
        assert config["credential_source"] == "project_env"
        assert config["base_url"] == "https://gateway.example/v1"
        assert config["api_key"] == "server-only-secret"
        assert config["model"] == "gpt-project-test"


def test_zhipu_validator_uses_eval_environment_without_exposing_key(monkeypatch) -> None:
    monkeypatch.setenv(
        "EQUIPMENT_EVAL_ZHIPU_BASE_URL",
        "https://yunwu.ai/v1",
    )
    monkeypatch.setenv("EQUIPMENT_EVAL_ZHIPU_API_KEY", "zhipu-server-secret")
    config = _validate_zhipu_llm_config(
        ZhipuLLMConfig(credential_source="eval_env", model="glm-5.2"),
        real=True,
    )
    assert config["provider"] == "zhipu"
    assert config["api_protocol"] == "chat_completions"
    assert config["base_url"] == "https://yunwu.ai/v1"
    assert config["api_key"] == "zhipu-server-secret"
    assert config["max_output_tokens"] == 8000


def test_project_environment_credentials_must_be_complete(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", "MISSING_PROJECT_KEY")
    monkeypatch.delenv("MISSING_PROJECT_KEY", raising=False)
    monkeypatch.delenv("EQUIPMENT_DR__API_KEY", raising=False)
    monkeypatch.delenv("EQUIPMENT_DR_API_KEY", raising=False)

    with pytest.raises(HTTPException) as error:
        _validate_generic_agent_config(
            GenericAgentConfig(credential_source="project_env"),
            real=True,
        )

    assert error.value.status_code == 422
    assert "API Key" in str(error.value.detail)


def test_benchmark_web_api_imports_local_queries_and_runs_fake_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project(tmp_path)
    workbook = _workbook(tmp_path / "local.xlsx", count=4)
    source = __import__("openpyxl").load_workbook(workbook)
    sheet = source["专家标注"]
    for row_number in range(5, 9):
        for column in range(16, 25):
            sheet.cell(row_number, column, "")
    source.save(workbook)
    monkeypatch.setenv("EQUIPMENT_EVAL_DEFAULT_WORKBOOK", str(workbook))
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)

    overview = client.get("/api/v1/benchmarks/overview")
    assert overview.status_code == 200
    assert overview.json()["default_workbook"]["available"] is True

    imported = client.post(
        "/api/v1/benchmarks/datasets/default-import",
        json={
            "dataset_id": "local-ui-test",
            "total": 4,
            "pilot_count": 1,
            "allow_unreviewed": True,
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["selection_mode"] == "local_candidate_test"

    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "web-api-smoke",
            "dataset_id": "local-ui-test",
            "systems": ["generic_agent"],
            "split": "pilot",
            "limit": 1,
            "mode": "fake",
            "judge_mode": "none",
        },
    )
    assert started.status_code == 202, started.text
    detail = None
    for _ in range(50):
        detail = client.get("/api/v1/benchmarks/runs/web-api-smoke").json()
        if detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert detail is not None
    assert detail["status"] == "completed"
    assert detail["results"][0]["system_id"] == "generic_agent"
    assert detail["results"][0]["status"] == "completed"


def test_benchmark_web_api_runs_and_saves_fake_zhipu_baseline(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "zhipu-baseline-smoke",
            "dataset_id": "fixture-smoke",
            "systems": ["zhipu_llm"],
            "split": "pilot",
            "limit": 1,
            "mode": "fake",
            "judge_mode": "none",
        },
    )
    assert started.status_code == 202, started.text
    detail = None
    for _ in range(50):
        detail = client.get(
            "/api/v1/benchmarks/runs/zhipu-baseline-smoke"
        ).json()
        if detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert detail is not None
    assert detail["status"] == "completed"
    assert detail["results"][0]["system_id"] == "zhipu_llm"
    reports = client.get(
        "/api/v1/benchmarks/reports?dataset_id=fixture-smoke"
    ).json()["reports"]
    assert any(row["system_id"] == "zhipu_llm" for row in reports)


def test_benchmark_web_api_lists_and_runs_manually_selected_queries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project(tmp_path)
    workbook = _workbook(tmp_path / "local.xlsx", count=4)
    source = __import__("openpyxl").load_workbook(workbook)
    sheet = source["专家标注"]
    for row_number in range(5, 9):
        for column in range(16, 25):
            sheet.cell(row_number, column, "")
    source.save(workbook)
    monkeypatch.setenv("EQUIPMENT_EVAL_DEFAULT_WORKBOOK", str(workbook))
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    imported = client.post(
        "/api/v1/benchmarks/datasets/default-import",
        json={
            "dataset_id": "manual-query-test",
            "total": 4,
            "pilot_count": 1,
            "allow_unreviewed": True,
        },
    )
    assert imported.status_code == 200, imported.text
    listed = client.get("/api/v1/benchmarks/datasets/manual-query-test/queries")
    assert listed.status_code == 200, listed.text
    assert listed.json()["query_count"] == 4
    assert set(listed.json()["queries"][0]) == {
        "query_id", "query", "region", "domain", "difficulty", "split"
    }
    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "manual-query-run",
            "dataset_id": "manual-query-test",
            "systems": ["generic_agent"],
            "query_ids": ["Q-0003", "Q-0001"],
            "split": "pilot",
            "limit": 1,
            "mode": "fake",
            "judge_mode": "none",
        },
    )
    assert started.status_code == 202, started.text
    detail = None
    for _ in range(50):
        detail = client.get("/api/v1/benchmarks/runs/manual-query-run").json()
        if detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert detail is not None
    assert detail["status"] == "completed"
    assert detail["selection_mode"] == "manual"
    assert detail["split"] == "manual"
    assert detail["limit"] == 2
    assert detail["selected_query_ids"] == ["Q-0003", "Q-0001"]
    assert [row["query_id"] for row in detail["results"]] == ["Q-0001", "Q-0003"]


def test_baseline_prepare_parallelizes_query_system_matrix_and_saves_reports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project(tmp_path)
    workbook = _workbook(tmp_path / "parallel-baselines.xlsx", count=4)
    source = __import__("openpyxl").load_workbook(workbook)
    sheet = source["专家标注"]
    for row_number in range(5, 9):
        for column in range(16, 25):
            sheet.cell(row_number, column, "")
    source.save(workbook)
    monkeypatch.setenv("EQUIPMENT_EVAL_DEFAULT_WORKBOOK", str(workbook))
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    imported = client.post(
        "/api/v1/benchmarks/datasets/default-import",
        json={
            "dataset_id": "parallel-baseline-test",
            "total": 4,
            "pilot_count": 2,
            "allow_unreviewed": True,
        },
    )
    assert imported.status_code == 200, imported.text

    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "parallel-baseline-prepare",
            "dataset_id": "parallel-baseline-test",
            "systems": ["generic_agent", "bare_llm"],
            "query_ids": ["Q-0001", "Q-0002"],
            "mode": "fake",
            "judge_mode": "none",
            "baseline_concurrency": 4,
        },
    )
    assert started.status_code == 202, started.text
    detail = None
    for _ in range(50):
        detail = client.get(
            "/api/v1/benchmarks/runs/parallel-baseline-prepare"
        ).json()
        if detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)

    assert detail is not None
    assert detail["status"] == "completed"
    assert detail["baseline_concurrency"] == 4
    assert detail["baseline_task_count"] == 4
    assert detail["run_result"]["scheduled_tasks"] == 4
    assert detail["run_result"]["parallel_workers"] == 4
    assert len(detail["saved_baseline_reports"]) == 4
    assert detail["display_name"].startswith("Baseline预生成 · ")
    assert "等2条" in detail["display_name"]
    assert {
        (row["query_id"], row["system_id"])
        for row in detail["saved_baseline_reports"]
    } == {
        ("Q-0001", "generic_agent"),
        ("Q-0001", "bare_llm"),
        ("Q-0002", "generic_agent"),
        ("Q-0002", "bare_llm"),
    }


def test_benchmark_reuses_completed_project_report_and_runs_only_baseline(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(
        create_benchmark_router(
            project,
            list_research_runs=lambda: [
                {
                    "run_id": "run-existing-1",
                    "topic": "评估公开资料条件下低空无人系统探测预警能力需求。",
                    "research_route": "auto",
                    "discovery_branch": "A",
                    "updated_at": "2026-07-20T00:00:00+00:00",
                    "report_available": True,
                }
            ],
            load_research_report=lambda run_id: {
                "answer": "# 已完成项目报告\n\n这是项目正常研究链路生成的报告。",
                "citations": ["https://example.org/project-evidence"],
                "sources": ["项目证据"],
                "duration_seconds": 321.0,
                "model_snapshot": {"model": "project-model"},
                "artifact_refs": [f"outputs/runs/{run_id}/report.md"],
            },
        )
    )
    client = TestClient(app)

    overview = client.get("/api/v1/benchmarks/overview").json()
    assert overview["research_runs"][0]["run_id"] == "run-existing-1"
    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "reuse-project-report",
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent"],
            "query_ids": ["Q-0001"],
            "project_runs": {"Q-0001": "run-existing-1"},
            "mode": "fake",
            "judge_mode": "fake",
            "pairwise_systems": ["generic_agent"],
        },
    )
    assert started.status_code == 202, started.text
    detail = None
    for _ in range(50):
        detail = client.get("/api/v1/benchmarks/runs/reuse-project-report").json()
        if detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert detail is not None
    assert detail["status"] == "completed"
    assert detail["full_method_source"] == "existing_research_run"
    assert detail["project_runs"] == {"Q-0001": "run-existing-1"}
    results = {row["system_id"]: row for row in detail["results"]}
    assert set(results) == {"full_method", "generic_agent"}
    assert results["full_method"]["answer"].startswith("# 已完成项目报告")
    assert results["full_method"]["duration_seconds"] == 321.0
    assert detail["run_result"]["system_count"] == 2
    assert detail["pair_result"]["pair_count"] == 2


def test_saved_baseline_reports_can_be_selected_for_later_judging_without_rerun(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(
        create_benchmark_router(
            project,
            list_research_runs=lambda: [{"run_id": "project-report-1", "topic": "fixture"}],
            load_research_report=lambda run_id: {
                "answer": "# 完整方法报告\n\n用于与已保存 baseline 报告进行评审。",
                "citations": [],
                "sources": [],
                "artifact_refs": [f"outputs/runs/{run_id}/report.md"],
            },
        )
    )
    client = TestClient(app)

    prepared = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "prepare-baseline-reports",
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent", "bare_llm"],
            "query_ids": ["Q-0001"],
            "mode": "fake",
            "judge_mode": "none",
        },
    )
    assert prepared.status_code == 202, prepared.text
    prepared_detail = None
    for _ in range(50):
        prepared_detail = client.get(
            "/api/v1/benchmarks/runs/prepare-baseline-reports"
        ).json()
        if prepared_detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert prepared_detail is not None
    assert prepared_detail["status"] == "completed"
    assert len(prepared_detail["saved_baseline_reports"]) == 2

    catalog = client.get(
        "/api/v1/benchmarks/reports?dataset_id=fixture-smoke"
    ).json()
    assert all(row["query"] for row in catalog["reports"])
    assert all(row["query"] for row in prepared_detail["saved_baseline_reports"])
    report_ids = {
        row["system_id"]: row["report_id"]
        for row in catalog["reports"]
        if row["query_id"] == "Q-0001"
    }
    assert set(report_ids) == {"generic_agent", "bare_llm"}
    for report_id in report_ids.values():
        report_dir = project / "outputs" / "evals" / "baseline-reports" / report_id
        assert (report_dir / "report.md").is_file()
        assert (report_dir / "report.json").is_file()
        assert client.get(f"/api/v1/benchmarks/reports/{report_id}").json()["answer"]

    def unexpected_build(*args, **kwargs):
        raise AssertionError("selected baseline reports must not rerun adapters")

    monkeypatch.setattr("evals.cli._build_adapter", unexpected_build)
    judged = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "judge-saved-baseline-reports",
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent", "bare_llm"],
            "query_ids": ["Q-0001"],
            "project_runs": {"Q-0001": "project-report-1"},
            "baseline_reports": {
                "Q-0001": {
                    "generic_agent": report_ids["generic_agent"],
                    "bare_llm": report_ids["bare_llm"],
                }
            },
            "mode": "real",
            "judge_mode": "fake",
            "pairwise_systems": ["generic_agent", "bare_llm"],
            "confirm_external_data": False,
        },
    )
    assert judged.status_code == 202, judged.text
    judged_detail = None
    for _ in range(50):
        judged_detail = client.get(
            "/api/v1/benchmarks/runs/judge-saved-baseline-reports"
        ).json()
        if judged_detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert judged_detail is not None
    assert judged_detail["status"] == "completed"
    assert judged_detail["baseline_execution_required"] == []
    assert judged_detail["run_result"]["scheduled_tasks"] == 0
    assert judged_detail["pair_result"]["pair_count"] == 4
    reused = [
        row for row in judged_detail["results"] if row["system_id"] != "full_method"
    ]
    assert all(row["model_snapshot"]["reused_baseline_report_id"] for row in reused)


def test_benchmark_record_metadata_crud_and_delete(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "record-crud-smoke",
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent"],
            "mode": "fake",
            "judge_mode": "none",
        },
    )
    assert started.status_code == 202, started.text
    detail = None
    for _ in range(50):
        detail = client.get("/api/v1/benchmarks/runs/record-crud-smoke").json()
        if detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert detail is not None
    assert detail["status"] == "completed"
    updated = client.patch(
        "/api/v1/benchmarks/runs/record-crud-smoke",
        json={"display_name": "Pilot 结果记录", "notes": "用于前端 CRUD 验证。"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "Pilot 结果记录"
    assert updated.json()["notes"] == "用于前端 CRUD 验证。"
    reread = client.get("/api/v1/benchmarks/runs/record-crud-smoke")
    assert reread.json()["display_name"] == "Pilot 结果记录"
    deleted = client.delete("/api/v1/benchmarks/runs/record-crud-smoke")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"eval_id": "record-crud-smoke", "deleted": True}
    assert client.get("/api/v1/benchmarks/runs/record-crud-smoke").status_code == 404
    assert not (project / "outputs" / "evals" / "record-crud-smoke").exists()


def test_benchmark_records_can_be_merged_into_one_history_entry(tmp_path: Path) -> None:
    project = _project(tmp_path)
    output_root = project / "outputs" / "evals"
    records = [
        ("final-eval", "real", "real"),
        ("prior-eval", "real", "real"),
        ("baseline-prepare", "real", "none"),
    ]
    for index, (eval_id, mode, judge_mode) in enumerate(records):
        target = output_root / eval_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "web-run.json").write_text(
            json.dumps(
                {
                    "eval_id": eval_id,
                    "dataset_id": "fixture-smoke",
                    "status": "completed",
                    "mode": mode,
                    "judge_mode": judge_mode,
                    "limit": 2,
                    "created_at": f"2026-07-30T00:0{index}:00+00:00",
                    "completed_at": f"2026-07-30T00:1{index}:00+00:00",
                }
            ),
            encoding="utf-8",
        )
    write_jsonl(
        output_root / "final-eval" / "results.jsonl",
        [
            EvalRunResult("final-eval", "Q-0001", "full_method", "completed", answer="完整方法").to_dict(),
            EvalRunResult("final-eval", "Q-0001", "generic_agent", "completed", answer="通用 Agent").to_dict(),
        ],
    )
    write_jsonl(
        output_root / "prior-eval" / "results.jsonl",
        [
            EvalRunResult("prior-eval", "Q-0001", "full_method", "completed", answer="旧完整方法").to_dict(),
            EvalRunResult("prior-eval", "Q-0001", "bare_llm", "completed", answer="纯 LLM").to_dict(),
        ],
    )
    (output_root / "final-eval" / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "baseline_order": ["generic_agent"],
                "comparisons": {"generic_agent": {"query_count": 1}},
            }
        ),
        encoding="utf-8",
    )
    (output_root / "prior-eval" / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "baseline_order": ["generic_agent", "bare_llm"],
                "comparisons": {
                    "generic_agent": {"query_count": 99},
                    "bare_llm": {"query_count": 1},
                },
            }
        ),
        encoding="utf-8",
    )
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    merged = client.post(
        "/api/v1/benchmarks/runs/final-eval/merge",
        json={
            "source_eval_ids": ["prior-eval", "baseline-prepare"],
            "display_name": "综合评测结果",
        },
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["merged_record_count"] == 3
    assert merged.json()["display_name"] == "综合评测结果"
    overview = client.get("/api/v1/benchmarks/overview").json()
    assert [row["eval_id"] for row in overview["runs"]] == ["final-eval"]
    detail = client.get("/api/v1/benchmarks/runs/final-eval").json()
    assert {row["eval_id"] for row in detail["merged_source_records"]} == {
        "prior-eval",
        "baseline-prepare",
    }
    assert detail["summary"]["baseline_order"] == ["generic_agent", "bare_llm"]
    assert detail["summary"]["comparisons"]["generic_agent"]["query_count"] == 1
    assert {row["system_id"] for row in detail["results"]} == {
        "full_method",
        "generic_agent",
        "bare_llm",
    }
    assert client.get("/api/v1/benchmarks/runs/prior-eval").status_code == 200


def test_multi_baseline_run_judges_each_baseline_separately(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project(tmp_path)

    def fake_run_systems(**kwargs):
        eval_root = Path(kwargs["output_root"]) / kwargs["eval_id"]
        eval_root.mkdir(parents=True, exist_ok=True)
        results_path = eval_root / "results.jsonl"
        write_jsonl(
            results_path,
            [
                EvalRunResult(kwargs["eval_id"], "Q-0001", "full_method", "completed", answer="完整方法回答").to_dict(),
                EvalRunResult(kwargs["eval_id"], "Q-0001", "generic_agent", "completed", answer="通用 Agent 回答").to_dict(),
                EvalRunResult(kwargs["eval_id"], "Q-0001", "bare_llm", "completed", answer="纯 LLM 回答").to_dict(),
            ],
        )
        return {
            "eval_id": kwargs["eval_id"],
            "query_count": 1,
            "system_count": 3,
            "result_count": 3,
            "completed": 3,
            "failed": 0,
            "results": str(results_path),
        }

    monkeypatch.setattr("evals.web_api.run_systems", fake_run_systems)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "multi-baseline-smoke",
            "dataset_id": "fixture-smoke",
            "systems": ["full_method", "generic_agent", "bare_llm"],
            "split": "pilot",
            "limit": 1,
            "mode": "fake",
            "judge_mode": "fake",
        },
    )
    assert started.status_code == 202, started.text
    assert started.json()["pairwise_systems"] == ["generic_agent", "bare_llm"]
    assert started.json()["pairwise_system"] == "generic_agent"
    detail = None
    for _ in range(50):
        detail = client.get("/api/v1/benchmarks/runs/multi-baseline-smoke").json()
        if detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert detail is not None
    assert detail["status"] == "completed"
    assert set(detail["pair_results"]) == {"generic_agent", "bare_llm"}
    assert detail["pair_result"]["pair_count"] == 4
    assert set(detail["judge_results"]) == {"generic_agent", "bare_llm"}
    summary = detail["summary"]
    assert summary["schema_version"] == "2.0"
    assert summary["baseline_order"] == ["generic_agent", "bare_llm"]
    for baseline, comparison in summary["comparisons"].items():
        assert set(comparison["systems"]) == {"full_method", baseline}
        assert comparison["judgment_count"] == 4
    eval_root = project / "outputs" / "evals" / "multi-baseline-smoke"
    for baseline in ("generic_agent", "bare_llm"):
        assert (eval_root / "pairs" / baseline / "pairs.public.jsonl").is_file()
        assert (eval_root / "pairs" / baseline / "pairs.admin.jsonl").is_file()
        assert (eval_root / f"judgments.{baseline}.jsonl").is_file()


def test_judge_rejects_pairwise_system_not_in_selected_systems(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    response = TestClient(app).post(
        "/api/v1/benchmarks/runs",
        json={
            "dataset_id": "fixture-smoke",
            "systems": ["full_method", "generic_agent"],
            "pairwise_systems": ["bare_llm"],
            "mode": "fake",
            "judge_mode": "fake",
        },
    )
    assert response.status_code == 422
    assert "baseline" in response.json()["detail"]


def test_real_benchmark_requires_external_data_confirmation(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    response = TestClient(app).post(
        "/api/v1/benchmarks/runs",
        json={
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent"],
            "mode": "real",
            "confirm_external_data": False,
        },
    )
    assert response.status_code == 422
    assert "显式确认" in response.json()["detail"]


def test_real_generic_agent_requires_explicit_custom_api_configuration(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    missing = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent"],
            "mode": "real",
            "judge_mode": "none",
            "confirm_external_data": True,
        },
    )
    assert missing.status_code == 422
    assert "API URL" in missing.json()["detail"]
    local_login = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent"],
            "mode": "real",
            "judge_mode": "none",
            "confirm_external_data": True,
            "generic_agent": {
                "auth_mode": "codex_login",
                "model": "gpt-5.5",
            },
        },
    )
    assert local_login.status_code == 422
    assert "自定义 API" in local_login.json()["detail"]


def test_baseline_fake_run_keeps_temporary_api_keys_out_of_artifacts(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    secret = "one-run-only-secret"
    agent_secret = "one-run-agent-secret"
    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "bare-llm-smoke",
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent", "bare_llm"],
            "pairwise_system": "bare_llm",
            "split": "pilot",
            "limit": 1,
            "mode": "fake",
            "judge_mode": "none",
            "generic_agent": {
                "auth_mode": "eval_api_key",
                "base_url": "https://gateway.example/v1",
                "api_key": agent_secret,
                "model": "gpt-5.5",
            },
            "bare_llm": {
                "api_protocol": "chat_completions",
                "base_url": "https://api.deepseek.com",
                "api_key": secret,
                "model": "deepseek-chat",
            },
        },
    )
    assert started.status_code == 202, started.text
    detail = None
    for _ in range(50):
        detail = client.get("/api/v1/benchmarks/runs/bare-llm-smoke").json()
        if detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert detail is not None
    assert detail["status"] == "completed"
    assert {row["system_id"] for row in detail["results"]} == {"generic_agent", "bare_llm"}
    assert detail["bare_llm"]["api_key_present"] is True
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (project / "outputs" / "evals" / "bare-llm-smoke").rglob("*")
        if path.is_file()
    )
    assert secret not in persisted
    assert agent_secret not in persisted


def test_real_bare_llm_rejects_unsafe_or_incomplete_configuration(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    response = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "dataset_id": "fixture-smoke",
            "systems": ["bare_llm"],
            "mode": "real",
            "confirm_external_data": True,
            "bare_llm": {
                "api_protocol": "chat_completions",
                "base_url": "http://gateway.example/v1",
                "api_key": "secret",
                "model": "model-id",
            },
        },
    )
    assert response.status_code == 422
    assert "HTTPS" in response.json()["detail"]


def test_real_judge_requires_external_data_confirmation_even_for_fake_systems(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    response = TestClient(app).post(
        "/api/v1/benchmarks/runs",
        json={
            "dataset_id": "fixture-smoke",
            "systems": ["full_method", "generic_agent"],
            "mode": "fake",
            "judge_mode": "real",
            "confirm_external_data": False,
        },
    )
    assert response.status_code == 422
    assert "真实评审" in response.json()["detail"]


def test_configured_real_judge_key_is_not_persisted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project(tmp_path)
    secret = "judge-one-run-secret"

    def fake_run_systems(**kwargs):
        eval_root = Path(kwargs["output_root"]) / kwargs["eval_id"]
        results_path = eval_root / "results.jsonl"
        write_jsonl(
            results_path,
            [
                EvalRunResult(kwargs["eval_id"], "Q-0001", "full_method", "completed", answer="回答 A").to_dict(),
                EvalRunResult(kwargs["eval_id"], "Q-0001", "generic_agent", "completed", answer="回答 B").to_dict(),
            ],
        )
        return {
            "eval_id": kwargs["eval_id"],
            "query_count": 1,
            "system_count": 2,
            "result_count": 2,
            "completed": 2,
            "failed": 0,
            "results": str(results_path),
        }

    def fake_judge_pair_file(pairs_path, prompt_path, output_path, **kwargs):
        rows = []
        for pair in read_jsonl(pairs_path):
            rows.append(
                {
                    "pair_id": pair["pair_id"],
                    "judge_id": "configured-expert",
                    "winner": "tie",
                    "confidence": 0.5,
                    "dimensions": {
                        "task_fulfillment": "tie",
                        "facts_and_citations": "tie",
                        "analysis_depth": "tie",
                        "equipment_demand_value": "tie",
                        "uncertainty": "tie",
                    },
                    "reason": "test",
                    "citation_issues": [],
                    "hard_failures": [],
                }
            )
        write_jsonl(output_path, rows)
        return {"judgment_count": len(rows), "error_count": 0, "judge_count": 1, "usage": {}}

    monkeypatch.setattr("evals.web_api.run_systems", fake_run_systems)
    monkeypatch.setattr("evals.web_api.judge_pair_file", fake_judge_pair_file)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "configured-judge-smoke",
            "dataset_id": "fixture-smoke",
            "systems": ["full_method", "generic_agent"],
            "pairwise_system": "generic_agent",
            "mode": "fake",
            "judge_mode": "real",
            "confirm_external_data": True,
            "judge_llm": {
                "runtime": "llm_api",
                "api_protocol": "chat_completions",
                "base_url": "https://api.deepseek.com",
                "api_key": secret,
                "model": "deepseek-chat",
                "replicas": 1,
            },
        },
    )
    assert started.status_code == 202, started.text
    detail = None
    for _ in range(50):
        detail = client.get("/api/v1/benchmarks/runs/configured-judge-smoke").json()
        if detail["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert detail is not None
    assert detail["status"] == "completed"
    assert detail["judge_llm"]["model"] == "deepseek-chat"
    assert detail["judge_llm"]["api_key_present"] is True
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (project / "outputs" / "evals" / "configured-judge-smoke").rglob("*")
        if path.is_file()
    )
    assert secret not in persisted


def test_benchmark_can_be_cancelled_and_reports_terminal_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project(tmp_path)

    def cancellable_run_systems(**kwargs):
        deadline = time.monotonic() + 2
        while not kwargs["cancel_requested"]() and time.monotonic() < deadline:
            time.sleep(0.01)
        return {
            "eval_id": kwargs["eval_id"],
            "query_count": 1,
            "system_count": 0,
            "result_count": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": kwargs["cancel_requested"](),
            "results": str(Path(kwargs["output_root"]) / kwargs["eval_id"] / "results.jsonl"),
        }

    monkeypatch.setattr("evals.web_api.run_systems", cancellable_run_systems)
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)
    started = client.post(
        "/api/v1/benchmarks/runs",
        json={
            "eval_id": "cancel-web-run",
            "dataset_id": "fixture-smoke",
            "systems": ["generic_agent"],
            "mode": "fake",
            "judge_mode": "none",
        },
    )
    assert started.status_code == 202
    cancelled = client.post("/api/v1/benchmarks/runs/cancel-web-run/cancel")
    assert cancelled.status_code == 202, cancelled.text
    detail = None
    for _ in range(100):
        detail = client.get("/api/v1/benchmarks/runs/cancel-web-run").json()
        if detail["status"] == "cancelled":
            break
        time.sleep(0.01)
    assert detail is not None
    assert detail["status"] == "cancelled"
    assert detail["stage"] == "cancelled"
    assert client.delete("/api/v1/benchmarks/runs/cancel-web-run").status_code == 200


def test_benchmark_result_detail_returns_full_untruncated_answer(tmp_path: Path) -> None:
    project = _project(tmp_path)
    eval_root = project / "outputs" / "evals" / "full-answer-run"
    eval_root.mkdir(parents=True)
    (eval_root / "web-run.json").write_text(
        '{"eval_id":"full-answer-run","status":"completed"}',
        encoding="utf-8",
    )
    full_answer = "完整报告" * 500
    write_jsonl(
        eval_root / "results.jsonl",
        [
            EvalRunResult(
                "full-answer-run",
                "Q-0001",
                "full_method",
                "completed",
                answer=full_answer,
            ).to_dict()
        ],
    )
    app = FastAPI()
    app.include_router(create_benchmark_router(project))
    client = TestClient(app)

    summary = client.get("/api/v1/benchmarks/runs/full-answer-run").json()
    assert summary["results"][0]["answer_truncated"] is True
    assert len(summary["results"][0]["answer"]) == 1200
    detail = client.get(
        "/api/v1/benchmarks/runs/full-answer-run/results/Q-0001/full_method"
    )
    assert detail.status_code == 200
    assert detail.json()["answer"] == full_answer
