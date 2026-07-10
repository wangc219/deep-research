from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import knowledgegraph.demand_discovery.autonomous_research as ar  # noqa: E402
from knowledgegraph.demand_discovery.domain.judgement import (  # noqa: E402
    JudgementItem,
    JudgementReport,
)
from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    AuditReport,
    CandidateDemand,
    DomainTraceEvent,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402


NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)


class AutonomousRealReporterPathTests(unittest.TestCase):
    def test_real_path_uses_reporter_not_template_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = _seed_store()
            provider = FakeProvider()
            provider.set_responses(
                [
                    FakeResponse(
                        tool_calls=[
                            {
                                "id": "call-report",
                                "name": "generate_demand_report",
                                "arguments": {
                                    "report_id": "report-cand-1",
                                    "candidate_id": "cand-1",
                                    "title": "Report",
                                    "body": "样本有限，因此只能形成阶段性判断。",
                                    "evidence_ids": ["ev-1"],
                                    "audit_id": "audit-1",
                                    "domain_trace_ids": ["dt-candidate", "dt-audit"],
                                    "report_context_bundle_id": "placeholder",
                                },
                            }
                        ]
                    ),
                    FakeResponse(text="done"),
                ]
            )

            def rewrite_bundle_id(context, state):
                bundle_id = next(iter(store.report_context_bundles))
                return ar.AssistantMessage(
                    content=[
                        ar.AssistantContentBlock(
                            type="tool_call",
                            id="call-report",
                            name="generate_demand_report",
                            arguments={
                                "report_id": "report-cand-1",
                                "candidate_id": "cand-1",
                                "title": "Report",
                                "body": "样本有限，因此只能形成阶段性判断。",
                                "evidence_ids": ["ev-1"],
                                "audit_id": "audit-1",
                                "domain_trace_ids": ["dt-candidate", "dt-audit"],
                                "report_context_bundle_id": bundle_id,
                            },
                        )
                    ]
                )

            provider.set_responses(
                [FakeResponse(factory=rewrite_bundle_id), FakeResponse(text="done")]
            )
            curator_provider = FakeProvider()
            curator_provider.set_responses(
                [
                    FakeResponse(
                        tool_calls=[
                            {
                                "id": "call-curate",
                                "name": "record_report_context_curation",
                                "arguments": {
                                    "bundle_id": "placeholder",
                                    "curated_items": [
                                        {
                                            "item_id": "cur-1",
                                            "material_ids": ["mat-evidence-ev-1"],
                                            "report_use": "core",
                                            "claim_summary": "存在阶段性能力缺口",
                                            "curation_reason": "evidence allowed by audit",
                                            "required_caveat": "样本有限",
                                        }
                                    ],
                                },
                            }
                        ]
                    ),
                    FakeResponse(text="done"),
                ]
            )
            with mock.patch.object(
                ar,
                "_render_autonomous_report_body",
                side_effect=AssertionError("template body used"),
            ):
                audit_summary, report_summary = asyncio.run(
                    ar._complete_autonomous_report_after_audit_async(
                        store,
                        loop_result=_loop_result(),
                        trace=[],
                        run_dir=root,
                        audit=store.audit_reports["audit-1"],
                        report_mode="real",
                        reporter_provider=provider,
                        curator_provider=curator_provider,
                        artifacts=ArtifactStore(root / "artifacts"),
                    )
                )

        self.assertEqual(audit_summary["audit_id"], "audit-1")
        self.assertEqual(report_summary["report_mode"], "real")
        self.assertEqual(report_summary["report_id"], "report-cand-1")
        self.assertIn("report-cand-1", store.demand_reports)
        self.assertEqual(store.demand_reports["report-cand-1"].body, "样本有限，因此只能形成阶段性判断。")


def _seed_store() -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source",
            source_name="Official",
            source_tier="A",
            source_type="official",
            publish_time=NOW,
            url_or_path="https://example.test/a",
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
            claim="claim",
            evidence_summary="summary",
            excerpt="正文窗口",
            source_location="text:abc#para:1",
            evidence_assessment="direct",
            created_by="reader",
            created_at=NOW,
        )
    )
    store.upsert_candidate(
        CandidateDemand(
            candidate_id="cand-1",
            title="Candidate",
            demand_statement="Need capability.",
            status="candidate_demand",
            evidence_ids=["ev-1"],
            open_questions=[],
            solution_signals=[],
            created_by="tester",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_judgement_report(
        JudgementReport(
            judgement_id="judge-1",
            round_id="round-1",
            consensus_points=[
                JudgementItem(
                    text="存在保障缺口",
                    worker_report_ids=["worker-1"],
                    evidence_ids=["ev-1"],
                )
            ],
            contradictions=[],
            partial_coverage=[],
            unique_insights=[],
            blind_spots=[],
            evidence_strength_map={"ev-1": "partial"},
            next_round_plan={},
            stop_or_continue="stop",
            rationale="stop",
            created_at=NOW,
        )
    )
    store.append_audit(
        AuditReport(
            audit_id="audit-1",
            candidate_id="cand-1",
            conclusion="needs_revision",
            scorecard={"evidence_support": {"evidence_reviews": {}}},
            comments="needs more evidence",
            required_rework=["样本有限"],
            created_by="auditor",
            created_at=NOW,
        )
    )
    store.append_trace(
        DomainTraceEvent(
            domain_trace_id="dt-candidate",
            trace_id="trace-1",
            event_type="candidate_synthesized",
            actor="research_loop",
            target_type="CandidateDemand",
            target_id="cand-1",
            input_refs=["ev-1"],
            output_refs=["cand-1"],
            summary="candidate synthesized",
            decision="synthesized",
            rationale="from judgement",
            model=None,
            prompt_id=None,
            tool_refs=[],
            runtime_event_id=None,
            created_at=NOW,
            payload={},
        )
    )
    store.append_trace(
        DomainTraceEvent(
            domain_trace_id="dt-audit",
            trace_id="trace-1",
            event_type="audit_completed",
            actor="auditor",
            target_type="AuditReport",
            target_id="audit-1",
            input_refs=["cand-1", "ev-1"],
            output_refs=["audit-1"],
            summary="audit completed",
            decision="needs_revision",
            rationale="样本有限",
            model=None,
            prompt_id=None,
            tool_refs=[],
            runtime_event_id=None,
            created_at=NOW,
            payload={},
        )
    )
    return store


def _loop_result() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "topic": "远海医疗保障能力缺口",
        "candidate_synthesis": {
            "status": "synthesized",
            "candidate_id": "cand-1",
            "judgement_id": "judge-1",
            "title": "Candidate",
            "demand_statement": "Need capability.",
            "evidence_ids": ["ev-1"],
            "open_questions": [],
        },
    }


if __name__ == "__main__":
    unittest.main()
