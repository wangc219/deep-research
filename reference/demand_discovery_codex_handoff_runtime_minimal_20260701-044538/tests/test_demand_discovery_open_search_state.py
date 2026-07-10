from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.open_search import (  # noqa: E402
    OpenSearchPlan,
    OpenSourceBodyArtifact,
    OpenSourceLead,
    SourceQualityAssessment,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class DemandDiscoveryOpenSearchStateTests(unittest.TestCase):
    def test_open_search_state_jsonl_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "domain.jsonl"
            store = DomainStore()
            store.upsert_open_search_plan(_plan())
            store.upsert_open_source_lead(_lead())
            store.upsert_open_source_body_artifact(_body())
            store.upsert_source_quality_assessment(_assessment())
            store.export_jsonl(path)

            loaded = DomainStore.load_jsonl(path)

        self.assertEqual(loaded.open_search_plans["osp-1"].to_dict(), _plan().to_dict())
        self.assertEqual(loaded.open_source_leads["osl-1"].lead_id, "osl-1")
        self.assertEqual(loaded.open_source_leads["osl-1"].quality_status, "accepted")
        self.assertEqual(
            loaded.open_source_body_artifacts["osb-1"].to_dict(),
            _body().to_dict(),
        )
        self.assertEqual(
            loaded.source_quality_assessments["qa-1"].to_dict(),
            _assessment().to_dict(),
        )

    def test_quality_assessment_rejects_refs_not_bound_to_lead_body(self) -> None:
        store = DomainStore()
        store.upsert_open_search_plan(_plan())
        store.upsert_open_source_lead(_lead())
        store.upsert_open_source_body_artifact(_body())

        with self.assertRaisesRegex(ValueError, "unknown basis_artifact_ref for lead"):
            store.upsert_source_quality_assessment(
                _assessment(basis_artifact_refs=["text:not-from-body"])
            )

    def test_unknown_statuses_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown OpenSearchPlan status"):
            _plan(status="maybe")
        with self.assertRaisesRegex(ValueError, "unknown OpenSourceLead quality_status"):
            _lead(quality_status="maybe")
        with self.assertRaisesRegex(ValueError, "unknown SourceQualityAssessment quality_level"):
            _assessment(quality_level="maybe")


def _plan(*, status: str = "planned") -> OpenSearchPlan:
    return OpenSearchPlan(
        plan_id="osp-1",
        run_id="run-1",
        round_id="round-1",
        topic="远海保障",
        trigger_judgement_id="judge-1",
        trigger_reason="白名单耗尽后补证",
        queries=["远海保障 缺口"],
        allowed_result_count=3,
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def _lead(*, quality_status: str = "pending") -> OpenSourceLead:
    return OpenSourceLead(
        lead_id="osl-1",
        plan_id="osp-1",
        run_id="run-1",
        round_id="round-1",
        topic="远海保障",
        url="https://open.example.test/report",
        domain="open.example.test",
        title="Open report",
        snippet="公开报告",
        source_name_guess="Open Example",
        search_query="远海保障 缺口",
        source_scope="open_web",
        quality_status=quality_status,
        created_at=NOW,
        updated_at=NOW,
    )


def _body() -> OpenSourceBodyArtifact:
    return OpenSourceBodyArtifact(
        body_id="osb-1",
        lead_id="osl-1",
        plan_id="osp-1",
        url="https://open.example.test/report",
        final_url="https://open.example.test/report",
        content_type="text/html; charset=utf-8",
        artifact_ref="html:raw",
        simplified_ref="text:body",
        body_location_prefix="text:body#",
        fetched_by="reader",
        created_at=NOW,
    )


def _assessment(
    *,
    basis_artifact_refs: list[str] | None = None,
    quality_level: str = "usable",
) -> SourceQualityAssessment:
    return SourceQualityAssessment(
        assessment_id="qa-1",
        lead_id="osl-1",
        url="https://open.example.test/report",
        domain="open.example.test",
        basis_artifact_refs=basis_artifact_refs or ["text:body"],
        body_location_refs=["text:body#para:0"],
        read_document_ref="text:body",
        source_identity="Open Example",
        publisher_or_org="Open Example Institute",
        author="",
        publish_time="2026-06-20",
        is_original_source=True,
        citation_or_reference_signal="self-published report",
        content_type="article",
        quality_level=quality_level,
        risk_flags=[],
        reason="正文可读且发布主体清晰",
        created_by="tester",
        created_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
