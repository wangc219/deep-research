from unittest.mock import AsyncMock

import pytest

from platform_core.services.knowledge_graph_acceptance_service import (
    REQUIRED_ACCEPTANCE_CRITERIA,
    KnowledgeGraphAcceptanceService,
)


def _report(*, failed: set[str]) -> dict:
    stats = _stats()
    criteria = [
        {
            "id": criterion_id,
            "passed": criterion_id not in failed,
            **({"actual": stats[criterion_id]} if criterion_id in stats else {}),
        }
        for criterion_id in sorted(REQUIRED_ACCEPTANCE_CRITERIA)
    ]
    return {
        "acceptance_contract": "defense-kg-pilot-acceptance-v5",
        "passed": not failed,
        "criteria": criteria,
        "failed_criteria": [item["id"] for item in criteria if not item["passed"]],
    }


def _stats() -> dict:
    return {
        "source_documents": 1000,
        "paper_documents": 1000,
        "patent_documents": 0,
        "documents_with_build_runs": 1000,
        "accepted_entities": 5000,
        "accepted_relations": 20000,
        "duplicate_relation_mentions_excluded": True,
        "unreviewed_hypotheses_excluded": True,
    }


@pytest.mark.asyncio
async def test_acceptance_status_fails_closed_without_registered_evaluation():
    repository = AsyncMock()
    repository.collect_pilot_stats.return_value = _stats()
    repository.get_build_run_summary.return_value = {"completed": 1}
    repository.get_latest_evaluation.return_value = None
    service = KnowledgeGraphAcceptanceService(repository=repository)

    result = await service.get_status("kb-1")

    assert result["passed"] is False
    assert result["failed_criteria"] == ["evaluation_missing"]
    assert result["latest_evaluation"] is None


@pytest.mark.asyncio
async def test_acceptance_status_fails_closed_for_legacy_contract():
    repository = AsyncMock()
    repository.collect_pilot_stats.return_value = _stats()
    repository.get_build_run_summary.return_value = {"completed": 1}
    repository.get_latest_evaluation.return_value = {
        "status": "passed",
        "report": {"acceptance_contract": "defense-kg-pilot-acceptance-v1", "passed": True},
    }
    service = KnowledgeGraphAcceptanceService(repository=repository)

    result = await service.get_status("kb-1")

    assert result["passed"] is False
    assert result["failed_criteria"] == ["evaluation_contract_outdated"]


@pytest.mark.asyncio
async def test_acceptance_status_rechecks_current_authoritative_stats():
    repository = AsyncMock()
    repository.collect_pilot_stats.return_value = {**_stats(), "accepted_relations": 19999}
    repository.get_build_run_summary.return_value = {"completed": 1}
    repository.get_latest_evaluation.return_value = {
        "status": "passed",
        "report": _report(failed=set()),
    }
    service = KnowledgeGraphAcceptanceService(repository=repository)

    result = await service.get_status("kb-1")

    assert result["snapshot_contract"] == "defense-kg-authoritative-acceptance-snapshot-v2"
    assert result["requirements"]["source_documents"] == 1000
    assert result["requirements"]["paper_documents"] == 1000
    assert result["requirements"]["patent_documents"] == 0
    assert result["passed"] is False
    assert result["failed_criteria"] == ["authoritative_state_drift"]


@pytest.mark.asyncio
async def test_acceptance_service_validates_and_records_consistent_report():
    repository = AsyncMock()
    repository.record_evaluation.return_value = "evaluation-1"
    repository.collect_pilot_stats.return_value = _stats()
    service = KnowledgeGraphAcceptanceService(repository=repository)
    report = _report(failed={"entity_f1"})

    result = await service.record_evaluation(
        kb_id="kb-1",
        pipeline_revision="hybrid-v2-r1",
        gold_manifest_sha256="a" * 64,
        prediction_sha256="b" * 64,
        report=report,
        created_by="reviewer",
    )

    assert result == {"evaluation_id": "evaluation-1", "status": "failed"}
    repository.record_evaluation.assert_awaited_once()


@pytest.mark.asyncio
async def test_acceptance_service_rejects_fabricated_pass_flag():
    repository = AsyncMock()
    repository.collect_pilot_stats.return_value = _stats()
    service = KnowledgeGraphAcceptanceService(repository=repository)
    report = _report(failed={"entity_f1"})
    report["passed"] = True

    with pytest.raises(ValueError, match="report.passed"):
        await service.record_evaluation(
            kb_id="kb-1",
            pipeline_revision="hybrid-v2-r1",
            gold_manifest_sha256="a" * 64,
            prediction_sha256="b" * 64,
            report=report,
            created_by="reviewer",
        )
