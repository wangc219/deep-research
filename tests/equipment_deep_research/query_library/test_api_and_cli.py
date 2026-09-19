from __future__ import annotations

import base64
from io import BytesIO
import json
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from equipment_deep_research.api.app import create_app as create_research_app
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.query_library.api import create_app
from equipment_deep_research.query_library.cli import main
from equipment_deep_research.query_library.persistence import QueryLibraryRepository
from equipment_deep_research.query_library.service import QueryLibraryService


def test_api_manual_crud_and_async_generation_submission(tmp_path: Path) -> None:
    repository = QueryLibraryRepository(
        create_database_engine(f"sqlite:///{tmp_path / 'api.db'}")
    )
    artifact_root = tmp_path / "codex-homes"
    client = TestClient(
        create_app(QueryLibraryService(repository, artifact_root=artifact_root))
    )

    created = client.post(
        "/api/v1/query-library/queries",
        json={
            "query": "研究低空无人火力装备的体系能力需求。",
            "generation_rationale": "从低空作战痛点形成装备研究任务。",
            "source_references": [
                {
                    "title": "公开资料",
                    "url": "https://example.test/low-altitude?token=secret&id=3",
                    "relevance_note": "提供术语线索。",
                }
            ],
        },
    )
    assert created.status_code == 201
    assert created.json()["source_references"][0]["url"].endswith("?id=3")

    query_id = created.json()["query_id"]
    updated = client.patch(
        f"/api/v1/query-library/queries/{query_id}",
        json={"expected_version": 1, "supplemental_information": "增加体系韧性分析。"},
    )
    assert updated.status_code == 200
    published = client.post(
        f"/api/v1/query-library/queries/{query_id}/publish",
        json={"expected_version": 2},
    )
    assert published.json()["status"] == "published"
    listed = client.get(
        "/api/v1/query-library/queries", params={"status": "published"}
    ).json()
    assert listed["total"] == 1

    deleted = client.delete(f"/api/v1/query-library/queries/{query_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/query-library/queries/{query_id}").status_code == 404
    assert client.delete(f"/api/v1/query-library/queries/{query_id}").status_code == 404

    generation = client.post(
        "/api/v1/query-library/generations",
        headers={"Idempotency-Key": "generation-1"},
        json={
            "topic": "精确打击装备",
            "reference_urls": ["https://example.test/military?id=1&token=secret"],
        },
    )
    duplicate = client.post(
        "/api/v1/query-library/generations",
        headers={"Idempotency-Key": "generation-1"},
        json={"topic": "精确打击装备"},
    )
    assert generation.status_code == 202
    assert generation.json()["reference_urls"] == ["https://example.test/military?id=1"]
    assert duplicate.json()["generation_id"] == generation.json()["generation_id"]
    assert generation.json()["status"] == "queued"
    generation_list = client.get(
        "/api/v1/query-library/generations", params={"status": "queued", "limit": 10}
    )
    assert generation_list.status_code == 200
    assert generation_list.json()["items"][0]["generation_id"] == generation.json()["generation_id"]

    configured = client.post(
        "/api/v1/query-library/generations",
        json={
            "topic": "海上无人平台与导弹融合",
            "count": 20,
            "model_config": {
                "provider": "responses",
                "model": "gpt-5.5",
                "reasoning_effort": "high",
            },
        },
    )
    assert configured.status_code == 202
    assert configured.json()["requested_count"] == 20
    assert configured.json()["model_config"]["model"] == "gpt-5.5"
    blocked_delete = client.delete(
        f"/api/v1/query-library/generations/{generation.json()['generation_id']}"
    )
    assert blocked_delete.status_code == 409
    cancelled = client.post(
        f"/api/v1/query-library/generations/{configured.json()['generation_id']}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    artifact_directory = artifact_root / (
        "query-gen-" + configured.json()["generation_id"].removeprefix("generation-")
    )
    artifact_directory.mkdir(parents=True)
    (artifact_directory / "local-output.json").write_text("{}", encoding="utf-8")
    deleted = client.delete(
        f"/api/v1/query-library/generations/{configured.json()['generation_id']}"
    )
    assert deleted.status_code == 204
    assert not artifact_directory.exists()
    assert client.get(
        f"/api/v1/query-library/generations/{configured.json()['generation_id']}"
    ).status_code == 404

    invalid_reference = client.post(
        "/api/v1/query-library/generations",
        json={
            "topic": "精确打击装备",
            "reference_urls": ["http://localhost/private-report"],
        },
    )
    assert invalid_reference.status_code == 422
    assert "HTTPS" in invalid_reference.json()["detail"]


def test_generation_delete_handles_missing_artifacts_and_directory_symlinks(
    tmp_path: Path,
) -> None:
    repository = QueryLibraryRepository(
        create_database_engine(f"sqlite:///{tmp_path / 'delete-api.db'}")
    )
    artifact_root = tmp_path / "codex-homes"
    client = TestClient(
        create_app(QueryLibraryService(repository, artifact_root=artifact_root))
    )

    missing = client.post(
        "/api/v1/query-library/generations", json={"topic": "缺失目录删除测试"}
    ).json()
    client.post(
        f"/api/v1/query-library/generations/{missing['generation_id']}/cancel"
    )
    assert client.delete(
        f"/api/v1/query-library/generations/{missing['generation_id']}"
    ).status_code == 204

    linked = client.post(
        "/api/v1/query-library/generations", json={"topic": "链接目录删除测试"}
    ).json()
    client.post(
        f"/api/v1/query-library/generations/{linked['generation_id']}/cancel"
    )
    outside = tmp_path / "must-survive"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    artifact_root.mkdir(parents=True, exist_ok=True)
    link = artifact_root / (
        "query-gen-" + linked["generation_id"].removeprefix("generation-")
    )
    link.symlink_to(outside, target_is_directory=True)

    assert client.delete(
        f"/api/v1/query-library/generations/{linked['generation_id']}"
    ).status_code == 204
    assert not link.exists()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_cli_add_list_and_show_share_the_same_database(tmp_path: Path, capsys) -> None:
    database_url = f"sqlite:///{tmp_path / 'cli.db'}"
    assert (
        main(
            [
                "--database-url",
                database_url,
                "add",
                "--query",
                "研究精确打击装备的智能化能力需求。",
                "--generation-rationale",
                "人工录入测试。",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)

    assert main(["--database-url", database_url, "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["total"] == 1

    assert main(["--database-url", database_url, "show", created["query_id"]]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["query_id"] == created["query_id"]


def test_api_imports_query_workbook_and_numbered_long_text(tmp_path: Path) -> None:
    repository = QueryLibraryRepository(
        create_database_engine(f"sqlite:///{tmp_path / 'imports.db'}")
    )
    client = TestClient(create_app(QueryLibraryService(repository)))
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "50个前沿方向"
    sheet.append(["说明", "人工整理"])
    sheet.append([])
    sheet.append([])
    sheet.append(
        ["序号", "一级领域", "研究方向", "核心研究重点 / 制胜机理", "重点层级"]
    )
    sheet.append(
        [1, "复杂信息环境", "弱通信精确打击研究", "保持任务闭环。", "核心优先"]
    )
    buffer = BytesIO()
    workbook.save(buffer)

    imported_file = client.post(
        "/api/v1/query-library/imports/file",
        json={
            "filename": "前沿方向.xlsx",
            "content_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        },
    )
    assert imported_file.status_code == 201
    assert imported_file.json()["imported_count"] == 1
    file_item = imported_file.json()["items"][0]
    assert file_item["status"] == "published"
    assert file_item["source_type"] == "import"
    assert file_item["supplemental_information"] == "保持任务闭环。"
    assert "复杂信息环境" in file_item["generation_rationale"]
    assert "第 5 行" in file_item["source_references"][0]["relevance_note"]

    imported_text = client.post(
        "/api/v1/query-library/imports/text",
        json={
            "source_name": "分类长问题",
            "content": (
                "1、深度研究现代战争全链条制胜机理。\n"
                "\n四、市场需求深度挖掘高潜力方向-分类提问\n"
                "1、【局部战争启示】深度研究局部冲突下无人系统运用。\n"
                "2、【国际形势】深度研究潜在威胁与装备能力需求。"
            ),
        },
    )
    assert imported_text.status_code == 201
    assert imported_text.json()["imported_count"] == 3
    queries = [item["query"] for item in imported_text.json()["items"]]
    assert all("四、市场需求" not in item for item in queries)
    assert queries[1].startswith("【局部战争启示】")

    duplicate = client.post(
        "/api/v1/query-library/imports/text",
        json={"content": "1、深度研究现代战争全链条制胜机理。"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["skipped_count"] == 1


def test_main_api_mounts_query_library_and_traces_published_query(
    tmp_path: Path,
) -> None:
    repository = QueryLibraryRepository(
        create_database_engine(f"sqlite:///{tmp_path / 'mounted-query-library.db'}")
    )
    query_service = QueryLibraryService(repository)
    client = TestClient(
        create_research_app(
            ResearchApplicationService(), query_library_service=query_service
        )
    )

    assert client.get("/api/v1/query-library/health").status_code == 200
    draft = client.post(
        "/api/v1/query-library/queries",
        json={"query": "研究低空无人装备的体系能力缺口。"},
    ).json()
    rejected = client.post(
        "/api/v1/runs",
        json={
            "topic": draft["query"],
            "source_query_id": draft["query_id"],
            "source_query_version": draft["version"],
        },
    )
    assert rejected.status_code == 409

    auto_draft = client.post(
        "/api/v1/query-library/queries",
        json={"query": "自动审核低空无人装备需求研究。"},
    ).json()
    auto_created = client.post(
        "/api/v1/runs",
        json={
            "topic": auto_draft["query"],
            "source_query_id": auto_draft["query_id"],
            "source_query_version": auto_draft["version"],
            "publish_source_query_on_create": True,
        },
    )
    assert auto_created.status_code == 201
    auto_published = client.get(
        f"/api/v1/query-library/queries/{auto_draft['query_id']}"
    ).json()
    assert auto_published["status"] == "published"
    assert auto_published["version"] == auto_draft["version"] + 1
    assert auto_created.json()["execution"]["query_library"] == {
        "query_id": auto_draft["query_id"],
        "version": auto_published["version"],
        "source_type": "manual",
    }

    published = client.post(
        f"/api/v1/query-library/queries/{draft['query_id']}/publish",
        json={"expected_version": draft["version"]},
    ).json()
    created = client.post(
        "/api/v1/runs",
        json={
            "topic": published["query"],
            "source_query_id": published["query_id"],
            "source_query_version": published["version"],
        },
    )

    assert created.status_code == 201
    assert created.json()["execution"]["query_library"] == {
        "query_id": published["query_id"],
        "version": published["version"],
        "source_type": "manual",
    }

    long_topic = "面向高端战争研究无人远程精确打击装备体系能力需求。" * 21
    long_created = client.post("/api/v1/runs", json={"topic": long_topic})
    assert len(long_topic) > 500
    assert long_created.status_code == 201
    assert long_created.json()["topic"] == long_topic
