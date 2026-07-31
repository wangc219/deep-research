from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.autonomous_research import (  # noqa: E402
    _complete_autonomous_audit_and_report,
    _run_real_audit_worker,
)
from knowledgegraph.demand_discovery.domain.audit_rubric import load_default_rubric  # noqa: E402
from knowledgegraph.demand_discovery.domain.judgement import (  # noqa: E402
    JudgementItem,
    JudgementReport,
)
from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    CandidateDemand,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class AutonomousRealAuditWorkerTests(unittest.TestCase):
    def test_real_path_helper_rejects_programmatic_approved_audit(self) -> None:
        store = _store_with_candidate()
        loop_result = {
            "candidate_synthesis": {
                "status": "synthesized",
                "candidate_id": "cand-1",
                "judgement_id": "judge-1",
                "title": "Candidate",
                "demand_statement": "远海保障需要补足能力缺口",
                "evidence_ids": ["ev-1"],
                "open_questions": [],
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "real path requires auditor worker"):
                _complete_autonomous_audit_and_report(
                    store,
                    loop_result=loop_result,
                    trace=[],
                    run_dir=Path(tmp),
                    audit_actor="real-auditor",
                    audit_comments="programmatic approved audit",
                    audit_reason="programmatic pass",
                    audit_mode="real",
                )

    def test_real_audit_worker_uses_run_audit_tool_and_writes_audit_report(self) -> None:
        store = _store_with_candidate()

        def provider_factory(_spec):
            provider = FakeProvider()
            provider.set_responses(
                [
                    FakeResponse(
                        tool_calls=[
                            {
                                "id": "call-audit",
                                "name": "run_audit",
                                "arguments": {
                                    "audit_id": "audit-real-1",
                                    "candidate_id": "cand-1",
                                    "conclusion": "approved",
                                    "scorecard": _full_scorecard(
                                        evidence_support={
                                            "verdict": "pass",
                                            "reason": "direct body evidence supports the core conclusion",
                                            "evidence_reviews": {
                                                "ev-1": {
                                                    "evidence_id": "ev-1",
                                                    "support_level": "direct",
                                                    "support_type": "inferred_gap",
                                                    "used_for_core": True,
                                                    "reason": "正文段落直接说明能力缺口",
                                                    "missing_link": "",
                                                }
                                            },
                                        }
                                    ),
                                    "comments": "semantic audit completed",
                                    "required_rework": [],
                                },
                            }
                        ]
                    )
                ]
            )
            return provider

        with tempfile.TemporaryDirectory() as tmp:
            audit = asyncio.run(
                _run_real_audit_worker(
                    store=store,
                    run_id="run-1",
                    run_dir=Path(tmp),
                    candidate_id="cand-1",
                    judgement_id="judge-1",
                    report_core_conclusion="远海保障需要补足能力缺口",
                    provider_factory=provider_factory,
                )
            )

        self.assertEqual(audit.audit_id, "audit-real-1")
        self.assertEqual(audit.created_by, "auditor")
        self.assertIn("evidence_support", audit.scorecard)
        audit_events = [
            event for event in store.trace_events if event.event_type == "audit_completed"
        ]
        self.assertEqual(len(audit_events), 1)
        self.assertEqual(audit_events[0].payload["decision"], "approved")
        self.assertNotEqual(audit.created_by, "fixture-auditor")


def _full_scorecard(*, evidence_support: dict) -> dict:
    scorecard = {
        item_id: {"verdict": "pass", "reason": "default rubric item passed"}
        for item_id in load_default_rubric().item_ids
    }
    scorecard["evidence_support"] = evidence_support
    return scorecard


def _store_with_candidate() -> DomainStore:
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
            evidence_assessment="direct",
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
    store.upsert_judgement_report(
        JudgementReport(
            judgement_id="judge-1",
            round_id="round-1",
            consensus_points=[
                JudgementItem(text="远海保障缺口", worker_report_ids=["agent-1"], evidence_ids=["ev-1"])
            ],
            contradictions=[],
            partial_coverage=[],
            unique_insights=[],
            blind_spots=[],
            evidence_strength_map={"ev-1": "direct"},
            next_round_plan={},
            stop_or_continue="stop",
            rationale="stop",
            created_at=NOW,
        )
    )
    return store


if __name__ == "__main__":
    unittest.main()
