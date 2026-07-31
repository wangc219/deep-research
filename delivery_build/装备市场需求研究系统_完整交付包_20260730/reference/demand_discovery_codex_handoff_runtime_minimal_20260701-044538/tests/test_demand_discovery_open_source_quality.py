from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    AuditReport,
    CandidateDemand,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.open_search import (  # noqa: E402
    OpenSearchPlan,
    OpenSourceBodyArtifact,
    OpenSourceLead,
    SourceQualityAssessment,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import (  # noqa: E402
    create_assess_source_quality_tool,
    create_evidence_card_tool,
    create_source_record_tool,
)
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class DemandDiscoveryOpenSourceQualityTests(unittest.TestCase):
    def test_assess_source_quality_validates_refs_against_body_artifact(self) -> None:
        store = _store_with_open_lead()
        tool = create_assess_source_quality_tool(store)

        good = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "assess_source_quality",
                    _assessment_args(assessment_id="qa-good"),
                ),
                _ctx(),
            )
        )
        bad = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-2",
                    "assess_source_quality",
                    {
                        **_assessment_args(assessment_id="qa-bad"),
                        "basis_artifact_refs": ["text:fake"],
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(good.is_error)
        self.assertEqual(good.domain_proposals[0].object_type, "SourceQualityAssessment")
        self.assertTrue(bad.is_error)
        self.assertIn("unknown basis_artifact_ref for lead", bad.content)

    def test_source_record_rejects_evidence_collection_without_quality_assessment(self) -> None:
        store = _store_with_open_lead()
        tool = create_source_record_tool(store)

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "create_source_record",
                    {
                        "source_id": "src-open",
                        "title": "Open source",
                        "url_or_path": "https://open.example.test/report",
                        "open_source_lead_id": "osl-1",
                        "collection_decision": "use_as_evidence",
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("open source quality assessment is required", result.content)

    def test_open_source_evidence_requires_usable_quality_assessment(self) -> None:
        store = _store_with_open_source(quality_level="low_quality")
        tool = create_evidence_card_tool(store)

        rejected = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "create_evidence_card",
                    {
                        "evidence_id": "ev-open",
                        "source_id": "src-open",
                        "source_quality_assessment_id": "qa-open",
                        "claim": "远海保障存在缺口",
                        "evidence_summary": "正文提到保障短板",
                        "excerpt": "公开正文片段",
                        "source_location": "text:body#para:0",
                        "evidence_assessment": "strong",
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(rejected.is_error)
        self.assertIn("open source quality is rejected", rejected.content)

        store = _store_with_open_source(quality_level="usable")
        accepted = asyncio.run(
            create_evidence_card_tool(store).execute(
                ToolCall(
                    "call-2",
                    "create_evidence_card",
                    {
                        "evidence_id": "ev-open",
                        "source_id": "src-open",
                        "source_quality_assessment_id": "qa-open",
                        "claim": "远海保障存在缺口",
                        "evidence_summary": "正文提到保障短板",
                        "excerpt": "公开正文片段",
                        "source_location": "text:body#para:0",
                        "evidence_assessment": "strong",
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(accepted.is_error)
        self.assertEqual(
            accepted.domain_proposals[0].payload["source_quality_assessment_id"],
            "qa-open",
        )

    def test_report_gate_accepts_usable_open_source_and_rejects_provisional(self) -> None:
        usable = _store_with_report_candidate(quality_level="usable")
        usable.validate_demand_report_gate("cand-open", "audit-open", ["ev-open"])

        provisional = _store_with_report_candidate(quality_level="provisional")
        with self.assertRaisesRegex(ValueError, "minimum evidence requirement not met"):
            provisional.validate_demand_report_gate("cand-open", "audit-open", ["ev-open"])


def _store_with_open_lead() -> DomainStore:
    store = DomainStore()
    store.upsert_open_search_plan(
        OpenSearchPlan(
            plan_id="osp-1",
            run_id="run-1",
            round_id="round-1",
            topic="远海保障",
            trigger_judgement_id="judge-1",
            trigger_reason="白名单耗尽后补证",
            queries=["远海保障 缺口"],
            allowed_result_count=3,
            status="running",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_open_source_lead(
        OpenSourceLead(
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
            quality_status="pending",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_open_source_body_artifact(
        OpenSourceBodyArtifact(
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
    )
    return store


def _store_with_open_source(*, quality_level: str) -> DomainStore:
    store = _store_with_open_lead()
    store.upsert_source_quality_assessment(_assessment(quality_level=quality_level))
    store.upsert_source(_source_record(collection_decision="use_as_evidence"))
    return store


def _store_with_report_candidate(*, quality_level: str) -> DomainStore:
    store = _store_with_open_source(quality_level=quality_level)
    evidence = EvidenceCard(
        evidence_id="ev-open",
        source_id="src-open",
        claim="远海保障存在缺口",
        evidence_summary="正文提到保障短板",
        excerpt="公开正文片段",
        source_location="text:body#para:0",
        evidence_assessment="strong",
        created_by="reader",
        created_at=NOW,
        source_quality_assessment_id="qa-open",
    )
    store.upsert_evidence(evidence)
    store.upsert_candidate(
        CandidateDemand(
            candidate_id="cand-open",
            title="Open candidate",
            demand_statement="远海保障存在缺口",
            status="candidate_demand",
            evidence_ids=["ev-open"],
            open_questions=[],
            solution_signals=[],
            created_by="synthesis",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.append_audit(
        AuditReport(
            audit_id="audit-open",
            candidate_id="cand-open",
            conclusion="approved",
            scorecard={
                "evidence_support": {
                    "verdict": "pass",
                    "reason": "semantic audit",
                    "evidence_reviews": {
                        "ev-open": {
                            "evidence_id": "ev-open",
                            "support_level": "direct",
                            "support_type": "inferred_gap",
                            "used_for_core": True,
                            "reason": "open source body evidence supports the candidate",
                            "missing_link": "",
                        }
                    },
                },
                "evidence_supports_candidate": {
                    "verdict": "pass",
                    "reason": "cited evidence semantically supports the candidate",
                },
                "core_conclusion_supported": {
                    "verdict": "pass",
                    "reason": "core conclusion is directly supported",
                },
                "adjacent_evidence_limited": {
                    "verdict": "pass",
                    "reason": "no adjacent evidence is used as core support",
                },
                "unassessed_evidence_handled": {
                    "verdict": "pass",
                    "reason": "all cited evidence is assessed",
                },
            },
            comments="approved",
            required_rework=[],
            created_by="auditor",
            created_at=NOW,
        )
    )
    return store


def _assessment_args(*, assessment_id: str) -> dict[str, object]:
    return {
        "assessment_id": assessment_id,
        "lead_id": "osl-1",
        "basis_artifact_refs": ["text:body"],
        "body_location_refs": ["text:body#para:0"],
        "read_document_ref": "text:body",
        "source_identity": "Open Example",
        "publisher_or_org": "Open Example Institute",
        "author": "",
        "publish_time": "2026-06-20",
        "is_original_source": True,
        "citation_or_reference_signal": "self-published report",
        "content_type": "article",
        "quality_level": "usable",
        "risk_flags": [],
        "reason": "正文可读且发布主体清晰",
    }


def _assessment(*, quality_level: str) -> SourceQualityAssessment:
    return SourceQualityAssessment(
        assessment_id="qa-open",
        lead_id="osl-1",
        url="https://open.example.test/report",
        domain="open.example.test",
        basis_artifact_refs=["text:body"],
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


def _source_record(*, collection_decision: str) -> SourceRecord:
    return SourceRecord(
        source_id="src-open",
        title="Open report",
        source_name="Open Example",
        source_tier="B",
        source_type="open_web",
        publish_time=NOW,
        url_or_path="https://open.example.test/report",
        summary_text="summary",
        summary_source="model_generated",
        collection_decision=collection_decision,
        author_or_org="Open Example Institute",
        is_repost=False,
        original_source=None,
        institutional_stance=None,
        created_at=NOW,
        updated_at=NOW,
        open_source_lead_id="osl-1",
    )


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "reader", {})


if __name__ == "__main__":
    unittest.main()
