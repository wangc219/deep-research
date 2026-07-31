from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.autonomous_research import run_autonomous_research_sync  # noqa: E402


class DemandDiscoveryAutonomousE2EFakeTests(unittest.TestCase):
    def test_topic_only_fake_e2e_writes_audit_report_and_reconstructable_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = root / "source_whitelist.yaml"
            whitelist.write_text(
                """
version: 1
sources:
  - source_name: Official Source
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [低空, 无人机]
    default_queries: ["低空 无人机"]
    interaction_profile: static_listing
  - source_name: Journal Source
    source_tier: B
    source_type: journal
    hosts: [journal.example.test]
    fetch_transport: http
    entry_urls: ["https://journal.example.test/CN/"]
    topic_tags: [探测, 防护]
    default_queries: ["无人机 探测 防护"]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )

            result = run_autonomous_research_sync(
                mode="fake",
                topic="低空小型无人机威胁下的探测、预警与防护能力缺口",
                output_root=root / "runs",
                run_id="phase5-fake-e2e",
                max_rounds=2,
                source_whitelist_path=whitelist,
            )
            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            report_md = result.run_dir / "report.md"
            domain_text = result.domain_path.read_text(encoding="utf-8")
            trace_rows = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

            self.assertTrue(report_md.exists())
            self.assertIn("DemandReport", domain_text)
            self.assertIn("AuditReport", domain_text)
            for item in [
                "source_strategy",
                "research_round",
                "judgement",
                "candidate_synthesis",
                "audit",
                "report",
            ]:
                self.assertIn(item, summary["trace"])
            self.assertLess(summary["trace"].index("judgement"), summary["trace"].index("candidate_synthesis"))
            self.assertLess(summary["trace"].index("candidate_synthesis"), summary["trace"].index("audit"))
            self.assertLess(summary["trace"].index("audit"), summary["trace"].index("report"))
            self.assertEqual(summary["report"]["review_status"], "review_ready")
            report_trace_ids = summary["report"]["domain_trace_ids"]
            self.assertTrue(report_trace_ids)
            trace_by_id = {row["domain_trace_id"]: row for row in trace_rows}
            self.assertTrue(set(report_trace_ids).issubset(trace_by_id))
            report_event_types = [
                trace_by_id[trace_id]["event_type"]
                for trace_id in report_trace_ids
            ]
            for event_type in [
                "source_strategy_selected",
                "research_leads_recorded",
                "evidence_created",
                "worker_reports_recorded",
                "judgement_recorded",
                "candidate_synthesized",
                "audit_completed",
                "report_generated",
            ]:
                self.assertIn(event_type, report_event_types)


if __name__ == "__main__":
    unittest.main()
