from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from equipment_deep_research.query_library.factory import (
    _environment_default_status,
    _query_library_api_key,
    _query_library_base_url,
    default_seed_manifest,
)
from equipment_deep_research.query_library.credentials import EncryptedCredentialStore
from equipment_deep_research.query_library.models import (
    GeneratedCandidate,
    GenerationResult,
    SourceReference,
    VersionConflictError,
)
from equipment_deep_research.query_library.quality import coverage_plan
from equipment_deep_research.query_library.persistence import generation_jobs, provider_credentials
from equipment_deep_research.query_library.service import QueryLibraryService
from equipment_deep_research.query_library.worker import QueryGenerationWorker


SOURCE = SourceReference(
    title="公开来源",
    url="https://example.test/source",
    relevance_note="用于校验术语和发展方向。",
)


class SuccessfulGenerator:
    provider_snapshot = {"type": "fake", "model": "query-test"}

    async def generate(
        self,
        *,
        topic: str,
        supplemental_information: str,
        reference_urls: tuple[str, ...],
        count: int,
        existing_queries: list[str],
        on_stage,
    ) -> GenerationResult:
        del supplemental_information, reference_urls, existing_queries
        on_stage("web_validation")
        on_stage("query_generation")
        candidates = tuple(
            GeneratedCandidate(
                coverage_slot=slot,
                query=(
                    f"围绕{topic}的{slot}，深度研究未来作战任务、技术趋势、体系约束与"
                    f"实战效能，兼顾智能自主、传统现役跨代做优、新质蓝海颠覆拓新、"
                    f"低成本供应链和装备族规模发展，识别第{index}项装备能力需求并提出发展建议。"
                ),
                supplemental_information="从单装和体系两个层级开展分析。",
                generation_rationale="将需求牵引或技术驱动信号转化为装备能力研究问题。",
                source_references=(SOURCE,),
            )
            for index, slot in enumerate(coverage_plan(count), start=1)
        )
        return GenerationResult(
            candidates=candidates,
            source_references=(SOURCE,),
            provider_snapshot=self.provider_snapshot,
            search_queries=("无人远程火力 装备 规划",),
        )


class DuplicateGenerator(SuccessfulGenerator):
    async def generate(self, **kwargs) -> GenerationResult:
        result = await super().generate(**kwargs)
        duplicate = GeneratedCandidate(
            coverage_slot=result.candidates[0].coverage_slot,
            query="研究无人远程火力装备的体系能力需求。",
            supplemental_information="重复内容。",
            generation_rationale="用于验证原子回滚。",
            source_references=(SOURCE,),
        )
        return GenerationResult(
            candidates=(duplicate, *result.candidates[1:]),
            source_references=result.source_references,
            provider_snapshot=result.provider_snapshot,
        )


def test_manual_query_edit_revision_and_publish(
    query_service: QueryLibraryService,
) -> None:
    created = query_service.create_query(
        query="研究无人远程火力装备的体系能力需求。",
        generation_rationale="人工提出的研究方向。",
        source_references=[SOURCE],
    )
    updated = query_service.update_query(
        created.query_id,
        expected_version=1,
        supplemental_information="增加战损和弱网条件。",
    )
    published = query_service.set_status(
        created.query_id, status="published", expected_version=2
    )

    assert updated.version == 2
    assert published.status == "published"
    assert published.version == 3
    detail = query_service.get_query(created.query_id, include_revisions=True)
    assert len(detail["revisions"]) == 2
    with pytest.raises(VersionConflictError):
        query_service.update_query(
            created.query_id,
            expected_version=1,
            generation_rationale="stale edit",
        )


def test_worker_generates_twelve_drafts_atomically(
    query_service: QueryLibraryService,
) -> None:
    query_service.generator = SuccessfulGenerator()
    job = query_service.submit_generation(
        topic="无人远程火力打击装备",
        reference_urls=[
            "https://example.test/report?id=7&token=secret",
            "https://example.test/report?id=7&token=secret",
        ],
    )

    result = asyncio.run(
        QueryGenerationWorker(query_service, worker_id="test-worker").run_once()
    )

    assert result is not None
    assert result["generation_id"] == job.generation_id
    assert result["status"] == "completed"
    assert result["reference_urls"] == ["https://example.test/report?id=7"]
    assert len(result["result_query_ids"]) == 12
    assert result["search_queries"] == ["无人远程火力 装备 规划"]
    stored = query_service.list_queries(source_type="agent")
    assert stored["total"] == 12
    assert {item["status"] for item in stored["items"]} == {"draft"}
    assert all(item["generation_rationale"] for item in stored["items"])
    assert all(item["source_references"] for item in stored["items"])


def test_generation_supports_variable_count_and_task_level_model_config(
    query_service: QueryLibraryService,
) -> None:
    requested_configs: list[dict[str, str]] = []

    def generator_factory(config: dict[str, str]) -> SuccessfulGenerator:
        requested_configs.append(config)
        generator = SuccessfulGenerator()
        generator.provider_snapshot = {"type": config["provider"], "model": config["model"]}
        return generator

    query_service.generator_factory = generator_factory
    job = query_service.submit_generation(
        topic="海上无人平台与导弹融合",
        count=16,
        model_config={
            "provider": "responses",
            "model": "gpt-5.5",
            "reasoning_effort": "xhigh",
        },
    )

    completed = asyncio.run(
        query_service.process_generation(job.generation_id, worker_id="model-worker")
    )

    assert completed.status == "completed"
    assert len(completed.result_query_ids) == 16
    assert requested_configs == [
        {
            "provider": "responses",
            "model": "gpt-5.5",
            "reasoning_effort": "xhigh",
        }
    ]
    assert query_service.get_generation(job.generation_id)["model_config"] == {
        **requested_configs[0],
        "credential_configured": False,
    }
    assert completed.provider_snapshot["model"] == "gpt-5.5"


def test_custom_provider_credential_is_encrypted_and_redacted(
    query_service: QueryLibraryService, tmp_path: Path
) -> None:
    store = EncryptedCredentialStore(
        query_service.repository, tmp_path / "query-library.key"
    )
    query_service.credential_store = store
    job = query_service.submit_generation(
        topic="低空无人装备",
        model_config={
            "provider": "responses",
            "model": "gpt-5.5",
            "base_url": "https://example.test/v1/responses",
            "api_key": "sk-private-test-value",
        },
    )

    public = job.to_dict()["model_config"]
    assert public["credential_configured"] is True
    assert "credential_id" not in public
    assert "api_key" not in public
    assert store.resolve(job.model_config["credential_id"]) == "sk-private-test-value"
    with query_service.repository.engine.connect() as connection:
        encrypted = connection.execute(
            provider_credentials.select()
        ).mappings().one()["encrypted_secret"]
    assert "sk-private-test-value" not in encrypted
    assert (tmp_path / "query-library.key").stat().st_mode & 0o777 == 0o600


def test_query_generator_environment_defaults_prefer_module_specific_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_API_KEY", "project-key")
    monkeypatch.setenv("EQUIPMENT_DR_BASE_URL", "https://project.example/v1/responses")
    assert _query_library_api_key() == "project-key"
    assert _query_library_base_url() == "https://project.example/v1/responses"
    assert _environment_default_status()["api_key_source"] == "EQUIPMENT_DR_API_KEY"

    monkeypatch.setenv("EQUIPMENT_DR_QUERY_LIBRARY_API_KEY", "query-key")
    monkeypatch.setenv(
        "EQUIPMENT_DR_QUERY_LIBRARY_BASE_URL",
        "https://query.example/v1/responses",
    )
    assert _query_library_api_key() == "query-key"
    assert _query_library_base_url() == "https://query.example/v1/responses"
    status = _environment_default_status()
    assert status["api_key_source"] == "EQUIPMENT_DR_QUERY_LIBRARY_API_KEY"
    assert status["base_url_source"] == "EQUIPMENT_DR_QUERY_LIBRARY_BASE_URL"


def test_seed_manifest_is_idempotent(query_service: QueryLibraryService) -> None:
    first = query_service.import_seed_manifest(default_seed_manifest())
    second = query_service.import_seed_manifest(default_seed_manifest())

    assert first["imported_count"] >= 30
    assert second["imported_count"] == 0
    assert all(item["already_imported"] for item in second["sources"])
    stored = query_service.list_queries(source_type="import", limit=200)
    assert stored["total"] == first["imported_count"]
    assert all(item["status"] == "draft" for item in stored["items"])


def test_seed_manifest_replacement_archives_old_imported_queries(
    query_service: QueryLibraryService, tmp_path: Path
) -> None:
    query_service.repository.import_seed_records(
        source_name="legacy.md",
        source_fingerprint="legacy-v1",
        records=[
            {
                "query": "深度研究复杂电磁环境下远程精确打击装备的全部能力需求并形成体系建议。",
                "supplemental_information": "旧版长段落母题。",
                "generation_rationale": "旧版导入记录。",
                "source_references": [SOURCE.to_dict()],
            }
        ],
    )
    manifest = tmp_path / "replacement.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "replace_imported_queries": True,
                "sources": [
                    {
                        "source_name": "legacy.md",
                        "source_fingerprint": "short-v2",
                        "source_references": [SOURCE.to_dict()],
                        "records": [
                            {
                                "query": "复杂电磁环境自适应精打武器研究",
                                "supplemental_information": "研究动态干扰识别、工作模式切换、抗扰制导、降级运行和体系接口需求。",
                                "generation_rationale": "围绕长段落母题发散形成短研究选题。",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = query_service.import_seed_manifest(manifest)
    second = query_service.import_seed_manifest(manifest)
    stored = query_service.list_queries(source_type="import", limit=20)["items"]

    assert first["archived_count"] == 1
    assert first["imported_count"] == 1
    assert second["archived_count"] == 0
    assert second["imported_count"] == 0
    assert {item["query"]: item["status"] for item in stored} == {
        "深度研究复杂电磁环境下远程精确打击装备的全部能力需求并形成体系建议。": "archived",
        "复杂电磁环境自适应精打武器研究": "draft",
    }


def test_duplicate_generated_batch_fails_without_partial_inserts(
    query_service: QueryLibraryService,
) -> None:
    query_service.create_query(query="研究无人远程火力装备的体系能力需求。")
    query_service.generator = DuplicateGenerator()
    job = query_service.submit_generation(topic="无人远程火力打击装备")

    failed = asyncio.run(
        query_service.process_generation(job.generation_id, worker_id="worker-a")
    )

    assert failed.status == "failed"
    assert "DuplicateQueryError" in failed.error
    assert query_service.list_queries(source_type="agent")["total"] == 0


def test_expired_worker_lease_is_requeued_and_reclaimed(
    query_service: QueryLibraryService,
) -> None:
    job = query_service.submit_generation(topic="精确打击装备")
    first = query_service.repository.claim_generation(
        job.generation_id, worker_id="worker-old"
    )
    expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    with query_service.repository.engine.begin() as connection:
        connection.execute(
            generation_jobs.update()
            .where(generation_jobs.c.generation_id == job.generation_id)
            .values(lease_expires_at=expired)
        )

    reclaimed = query_service.repository.claim_next_generation(worker_id="worker-new")

    assert first.status == "running"
    assert reclaimed is not None
    assert reclaimed.generation_id == job.generation_id
    assert reclaimed.lease_owner == "worker-new"
    assert reclaimed.attempts == 2
