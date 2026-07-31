from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.autonomous_research import run_autonomous_research_sync  # noqa: E402


class DemandDiscoveryOpenSearchE2EFakeTests(unittest.TestCase):
    def test_fake_loop_records_open_search_lineage_before_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = root / "source_whitelist.yaml"
            whitelist.write_text(
                """
version: 1
sources:
  - source_name: Official Logistics
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [保障, 救援]
    default_queries: ["高寒 救援 保障"]
    interaction_profile: static_listing
  - source_name: Rescue Journal
    source_tier: B
    source_type: journal
    hosts: [journal.example.test]
    fetch_transport: http
    entry_urls: ["https://journal.example.test/CN/"]
    topic_tags: [救援, 医疗]
    default_queries: ["高寒地区 联合救援 医疗后送"]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )

            result = run_autonomous_research_sync(
                mode="fake",
                topic="高寒地区联合救援保障能力缺口",
                output_root=root / "runs",
                run_id="phase5-open-search-fake-e2e",
                max_rounds=2,
                source_whitelist_path=whitelist,
            )
            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            domain_rows = [
                json.loads(line)
                for line in result.domain_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            trace_rows = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        domain_types = [row["type"] for row in domain_rows if row.get("type")]
        self.assertIn("OpenSearchPlan", domain_types)
        self.assertIn("OpenSourceLead", domain_types)
        self.assertIn("OpenSourceBodyArtifact", domain_types)
        self.assertIn("SourceQualityAssessment", domain_types)
        self.assertIn("EvidenceCard", domain_types)
        self.assertGreaterEqual(len(summary.get("open_search_plans", [])), 1)

        event_types = [row["event_type"] for row in trace_rows]
        required_order = [
            "judgement_recorded",
            "open_search_plan_created",
            "open_source_lead_recorded",
            "source_quality_assessed",
            "candidate_synthesized",
            "audit_completed",
            "report_generated",
        ]
        positions = [event_types.index(item) for item in required_order]
        self.assertEqual(positions, sorted(positions))

        report = summary["report"]
        self.assertIsInstance(report, dict)
        input_refs = []
        for row in trace_rows:
            if row["event_type"] == "report_generated":
                input_refs = row["input_refs"]
                break
        self.assertTrue(any(ref.startswith("osp-") for ref in input_refs))
        self.assertTrue(any(ref.startswith("osl-") for ref in input_refs))
        self.assertTrue(any(ref.startswith("qa-") for ref in input_refs))
        self.assertTrue(set(report["domain_trace_ids"]))


if __name__ == "__main__":
    unittest.main()
