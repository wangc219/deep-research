from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    AuditReport,
    CandidateDemand,
    DomainTraceEvent,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.report_context import CuratedReportItem  # noqa: E402
from knowledgegraph.demand_discovery.harness.report_context import (  # noqa: E402
    ArtifactResolver,
    ContextIndexer,
    ContextVerifier,
)
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402


NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)


class ReportContextIndexerTests(unittest.TestCase):
    def test_indexer_uses_multi_root_artifacts_and_keeps_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing_store = ArtifactStore(root / "round-1")
            real_store = ArtifactStore(root / "round-2")
            text_ref = real_store.put(
                "第一段。\n\n第二段说明远海医疗保障存在能力缺口。\n\n第三段。",
                kind="text",
                meta={"title": "正文", "url": "https://official.example.test/a"},
            )
            store = _store(text_ref)

            pool = ContextIndexer(
                store,
                ArtifactResolver([missing_store, real_store]),
            ).build_candidate_pool(
                run_id="run-1",
                topic="远海医疗保障能力缺口",
                candidate_id="cand-1",
                judgement_id="judge-1",
                audit_id="audit-1",
                review_status="needs_revision",
            )

        rendered = "\n".join(item.window_text for item in pool.materials)
        lineage_types = [item["event_type"] for item in pool.lineage_trace]

        self.assertIn("第二段说明远海医疗保障存在能力缺口", rendered)
        self.assertNotIn("<html", rendered.lower())
        self.assertIn("candidate_synthesized", lineage_types)
        self.assertIn("audit_completed", lineage_types)
        self.assertEqual(pool.allowed_evidence_ids, ["ev-1"])
        self.assertIn("样本有限", pool.required_caveats)

    def test_context_verifier_allows_curator_to_exclude_any_known_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_store = ArtifactStore(root / "artifacts")
            text_ref = artifact_store.put(
                "第一段。\n\n第二段说明远海医疗保障存在能力缺口。",
                kind="text",
                meta={"title": "正文", "url": "https://official.example.test/a"},
            )
            pool = ContextIndexer(
                _store(text_ref),
                artifact_store,
            ).build_candidate_pool(
                run_id="run-1",
                topic="远海医疗保障能力缺口",
                candidate_id="cand-1",
                judgement_id="judge-1",
                audit_id="audit-1",
                review_status="needs_revision",
            )
            material_id = pool.materials[0].material_id

            verified = ContextVerifier().verify(
                pool,
                curated_items=[
                    CuratedReportItem(
                        item_id="cur-exclude-1",
                        material_ids=[material_id],
                        report_use="exclude",
                        claim_summary="排除不进入报告正文",
                        curation_reason="材料与核心报告用途不匹配",
                        excluded_reason="不作为正文材料使用",
                    )
                ],
            )

        self.assertTrue(verified.ok)


def _store(text_ref: str) -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="官方正文",
            source_name="Official",
            source_tier="A",
            source_type="official",
            publish_time=NOW,
            url_or_path="https://official.example.test/a",
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
            claim="远海医疗保障存在能力缺口",
            evidence_summary="正文支持能力缺口",
            excerpt="第二段说明远海医疗保障存在能力缺口。",
            source_location=f"{text_ref}#para:1",
            evidence_assessment="direct",
            created_by="reader",
            created_at=NOW,
        )
    )
    store.upsert_candidate(
        CandidateDemand(
            candidate_id="cand-1",
            title="Candidate",
            demand_statement="远海医疗保障需要能力补齐",
            status="candidate_demand",
            evidence_ids=["ev-1"],
            open_questions=["还缺少近期公开案例"],
            solution_signals=[],
            created_by="synthesis",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.append_audit(
        AuditReport(
            audit_id="audit-1",
            candidate_id="cand-1",
            conclusion="needs_revision",
            scorecard={
                "evidence_support": {
                    "evidence_reviews": {
                        "ev-1": {"support_level": "partial", "used_for_core": True}
                    },
                    "blocked_claims": ["已形成成熟装备体系"],
                    "required_caveats": ["样本有限"],
                }
            },
            comments="样本有限，需要继续补证",
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


if __name__ == "__main__":
    unittest.main()
