from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.autonomous_research import (  # noqa: E402
    run_autonomous_research_sync,
)


class AutonomousAuditSemanticE2EFakeTests(unittest.TestCase):
    def test_fake_run_audit_trace_has_fixture_mode_and_evidence_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_autonomous_research_sync(
                mode="fake",
                topic="远海医疗保障能力缺口",
                output_root=Path(tmp),
                run_id="audit-semantic-fake",
                max_rounds=2,
                seed_urls=None,
                allow_browser=False,
            )
            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            trace_rows = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            audit_events = [
                row for row in trace_rows if row.get("event_type") == "audit_completed"
            ]
            report_body = (result.run_dir / "report.md").read_text(encoding="utf-8")

        self.assertTrue(audit_events)
        self.assertEqual(audit_events[-1]["payload"]["audit_mode"], "fixture")
        self.assertIn("evidence_support", audit_events[-1]["payload"])
        self.assertTrue(summary["audit"])
        self.assertIn("evidence_support", summary["audit"]["scorecard"])
        self.assertEqual(summary["report"]["review_status"], "review_ready")
        self.assertIn("## 审计结论", report_body)
        self.assertIn("Fake autonomous audit approved", report_body)
        self.assertIn("## 必要返工", report_body)


if __name__ == "__main__":
    unittest.main()
