from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import DemandReport  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.report_publisher import publish_report  # noqa: E402


NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)


class ReportPublisherTests(unittest.TestCase):
    def test_publishes_readable_markdown_and_machine_manifest(self) -> None:
        store = DomainStore()
        store.demand_reports["report-1"] = DemandReport(
            report_id="report-1",
            candidate_id="cand-1",
            title="远海医疗保障能力缺口",
            body="## 核心判断\n\n样本有限，不能正式定论。",
            evidence_ids=["ev-1"],
            audit_id="audit-1",
            domain_trace_ids=["dt-candidate", "dt-audit", "dt-report"],
            created_at=NOW,
            review_status="needs_revision",
        )
        with tempfile.TemporaryDirectory() as tmp:
            published = publish_report(
                store,
                report_id="report-1",
                output_dir=Path(tmp),
                report_context_bundle_id="rcb-1",
            )
            report_md = published.report_md_path.read_text(encoding="utf-8")
            manifest = json.loads(published.manifest_path.read_text(encoding="utf-8"))

        self.assertIn("## 核心判断", report_md)
        self.assertIn("样本有限", report_md)
        self.assertNotIn("report_id:", report_md)
        self.assertNotIn("domain_trace_ids", report_md)
        self.assertEqual(manifest["report_id"], "report-1")
        self.assertEqual(manifest["report_context_bundle_id"], "rcb-1")
        self.assertEqual(manifest["review_status"], "needs_revision")
        self.assertEqual(manifest["evidence_ids"], ["ev-1"])
        self.assertEqual(manifest["domain_trace_ids"], ["dt-candidate", "dt-audit", "dt-report"])


if __name__ == "__main__":
    unittest.main()
