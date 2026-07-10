from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.report_context import (  # noqa: E402
    CuratedReportItem,
    ReportContextBundle,
    ReportContextMaterial,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)


class ReportContextModelTests(unittest.TestCase):
    def test_rejects_unknown_enum_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown material_type"):
            _material(material_type="raw")
        with self.assertRaisesRegex(ValueError, "unknown report_use"):
            _curated(report_use="main")

    def test_rejects_raw_html_windows(self) -> None:
        with self.assertRaisesRegex(ValueError, "raw HTML"):
            _material(window_text="<html><body>navigation</body></html>")

    def test_store_roundtrips_report_context_bundle(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "domain.jsonl"
            store = DomainStore()
            store.upsert_report_context_bundle(bundle)
            store.export_jsonl(path)
            loaded = DomainStore.load_jsonl(path)

        self.assertIn(bundle.bundle_id, loaded.report_context_bundles)
        self.assertEqual(
            loaded.report_context_bundles[bundle.bundle_id].to_dict(),
            bundle.to_dict(),
        )


def _material(
    *,
    material_type: str = "evidence",
    window_text: str = "第二段说明远海医疗保障存在能力缺口。",
) -> ReportContextMaterial:
    return ReportContextMaterial(
        material_id="mat-1",
        material_type=material_type,
        title="证据材料",
        summary="正文支持能力缺口",
        refs={"evidence_ids": ["ev-1"], "source_ids": ["src-1"]},
        window_text=window_text,
        source_location="text:abc#para:1",
        allowed_report_uses=["core", "support"],
        risk_flags=[],
    )


def _curated(*, report_use: str = "core") -> CuratedReportItem:
    return CuratedReportItem(
        item_id="cur-1",
        material_ids=["mat-1"],
        report_use=report_use,
        claim_summary="存在能力缺口",
        curation_reason="直接支撑候选需求",
    )


def _bundle() -> ReportContextBundle:
    return ReportContextBundle(
        bundle_id="rcb-1",
        run_id="run-1",
        topic="远海医疗保障能力缺口",
        candidate_id="cand-1",
        judgement_id="judge-1",
        audit_id="audit-1",
        review_status="needs_revision",
        control_brief={"required_rework": ["补充 direct evidence"]},
        lineage_trace=[{"domain_trace_id": "dt-1", "event_type": "audit_completed"}],
        materials=[_material()],
        curated_items=[_curated()],
        verifier_warnings=[],
        allowed_evidence_ids=["ev-1"],
        blocked_claims=["已形成成熟装备体系"],
        required_caveats=["样本有限"],
        created_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
