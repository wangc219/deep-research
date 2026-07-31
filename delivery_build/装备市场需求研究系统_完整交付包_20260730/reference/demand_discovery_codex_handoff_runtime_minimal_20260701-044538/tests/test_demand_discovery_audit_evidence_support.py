from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.audit_rubric import load_default_rubric  # noqa: E402
from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    CandidateDemand,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import run_audit_tool  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class DemandDiscoveryAuditEvidenceSupportTests(unittest.TestCase):
    def test_run_audit_schema_exposes_report_status_disposition_fields(self) -> None:
        tool = run_audit_tool(DomainStore(), rubric=load_default_rubric())

        support_schema = (
            tool.parameters_schema["properties"]["scorecard"]["properties"][
                "evidence_support"
            ]
        )
        support_properties = support_schema["properties"]

        self.assertIn("recommended_report_status", support_properties)
        self.assertIn("status_reason", support_properties)
        self.assertIn("recheck_conditions", support_properties)
        self.assertEqual(
            support_properties["recommended_report_status"]["enum"],
            ["review_ready", "needs_revision", "watchlist", "rejected"],
        )

    def test_run_audit_schema_exposes_evidence_review_map_shape(self) -> None:
        tool = run_audit_tool(DomainStore(), rubric=load_default_rubric())

        reviews_schema = (
            tool.parameters_schema["properties"]["scorecard"]["properties"][
                "evidence_support"
            ]["properties"]["evidence_reviews"]
        )
        review_schema = reviews_schema["additionalProperties"]

        self.assertEqual(reviews_schema["type"], "object")
        self.assertEqual(
            review_schema["required"],
            [
                "support_level",
                "support_type",
                "used_for_core",
                "reason",
                "missing_link",
            ],
        )
        self.assertEqual(
            review_schema["properties"]["support_level"]["enum"],
            ["direct", "partial", "adjacent", "weak", "irrelevant", "unassessed"],
        )
        self.assertEqual(
            review_schema["properties"]["support_type"]["enum"],
            [
                "explicit_demand",
                "inferred_gap",
                "context_only",
                "counter_evidence",
                "irrelevant",
            ],
        )
        self.assertEqual(review_schema["properties"]["used_for_core"]["type"], "boolean")

    def test_approved_audit_rejects_missing_evidence_support_scorecard(self) -> None:
        store = _store_with_candidate(evidence_assessment="direct")
        tool = run_audit_tool(store, rubric=load_default_rubric())

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "audit-call",
                    "run_audit",
                    {
                        "audit_id": "audit-1",
                        "candidate_id": "cand-1",
                        "conclusion": "approved",
                        "scorecard": _full_scorecard(evidence_support=None),
                        "comments": "approved without semantic evidence review",
                        "required_rework": [],
                    },
                ),
                ToolExecutionContext("run-1", "agent-1", "auditor"),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("missing evidence_support scorecard", result.content)

    def test_run_audit_accepts_direct_evidence_support_review(self) -> None:
        store = _store_with_candidate(evidence_assessment="direct")
        tool = run_audit_tool(store, rubric=load_default_rubric())
        scorecard = _full_scorecard(
            evidence_support={
                "verdict": "pass",
                "reason": "ev-1 is direct body evidence",
                "evidence_reviews": {
                    "ev-1": {
                        "evidence_id": "ev-1",
                        "support_level": "direct",
                        "support_type": "inferred_gap",
                        "used_for_core": True,
                        "reason": "正文直接说明能力缺口",
                        "missing_link": "",
                    }
                },
            }
        )

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "audit-call",
                    "run_audit",
                    {
                        "audit_id": "audit-1",
                        "candidate_id": "cand-1",
                        "conclusion": "approved",
                        "scorecard": scorecard,
                        "comments": "direct evidence supports candidate",
                        "required_rework": [],
                    },
                ),
                ToolExecutionContext("run-1", "agent-1", "auditor"),
            )
        )

        self.assertFalse(result.is_error)
        proposal = result.domain_proposals[0]
        self.assertEqual(proposal.payload["conclusion"], "approved")
        self.assertEqual(
            proposal.payload["scorecard"]["evidence_support"]["evidence_reviews"]["ev-1"]["support_level"],
            "direct",
        )
        trace = result.trace_proposals[0]
        self.assertEqual(trace.event_type, "audit_completed")
        self.assertIn("ev-1", trace.input_refs)
        self.assertEqual(trace.payload["evidence_support"]["verdict"], "pass")

    def test_run_audit_syncs_reviewed_support_level_to_evidence_card(self) -> None:
        store = _store_with_candidate(evidence_assessment="unreviewed")
        tool = run_audit_tool(store, rubric=load_default_rubric())
        scorecard = _full_scorecard(
            evidence_support={
                "verdict": "pass",
                "reason": "ev-1 is direct body evidence",
                "evidence_reviews": {
                    "ev-1": {
                        "evidence_id": "ev-1",
                        "support_level": "direct",
                        "support_type": "inferred_gap",
                        "used_for_core": True,
                        "reason": "正文直接说明能力缺口",
                        "missing_link": "",
                    }
                },
            }
        )

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "audit-call",
                    "run_audit",
                    {
                        "audit_id": "audit-1",
                        "candidate_id": "cand-1",
                        "conclusion": "approved",
                        "scorecard": scorecard,
                        "comments": "direct evidence supports candidate",
                        "required_rework": [],
                    },
                ),
                ToolExecutionContext("run-1", "agent-1", "auditor"),
            )
        )

        evidence_updates = [
            proposal
            for proposal in result.domain_proposals
            if proposal.object_type == "EvidenceCard"
        ]
        self.assertEqual(len(evidence_updates), 1)
        self.assertEqual(evidence_updates[0].payload["evidence_assessment"], "direct")
        self.assertTrue(
            any(
                trace.event_type == "evidence_updated"
                and trace.target_id == "ev-1"
                for trace in result.trace_proposals
            )
        )


def _store_with_candidate(*, evidence_assessment: str) -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source",
            source_name="Fixture",
            source_tier="A",
            source_type="official",
            publish_time=NOW,
            url_or_path="https://example.test/article",
            summary_text="summary",
            summary_source="manual",
            collection_decision="use_as_evidence",
            author_or_org=None,
            is_repost=False,
            original_source=None,
            institutional_stance=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_evidence(
        EvidenceCard(
            evidence_id="ev-1",
            source_id="src-1",
            claim="远海保障存在能力缺口",
            evidence_summary="正文说明能力缺口",
            excerpt="正文段落",
            source_location="text:article#para:3",
            evidence_assessment=evidence_assessment,
            created_by="reader",
            created_at=NOW,
        )
    )
    store.upsert_candidate(
        CandidateDemand(
            candidate_id="cand-1",
            title="Candidate",
            demand_statement="远海保障需要补足能力缺口",
            status="candidate_demand",
            evidence_ids=["ev-1"],
            open_questions=[],
            solution_signals=[],
            created_by="synthesis",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return store


def _full_scorecard(*, evidence_support: dict | None) -> dict:
    scorecard = {
        item_id: {"verdict": "pass", "reason": "default rubric item passed"}
        for item_id in load_default_rubric().item_ids
    }
    if evidence_support is not None:
        scorecard["evidence_support"] = evidence_support
    return scorecard


if __name__ == "__main__":
    unittest.main()
