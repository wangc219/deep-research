from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.autonomous_research import run_autonomous_research_sync  # noqa: E402


class AutonomousReporterE2EFakeTests(unittest.TestCase):
    def test_fake_report_marks_fixture_and_records_report_context_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = root / "source_whitelist.yaml"
            whitelist.write_text(_whitelist_yaml(), encoding="utf-8")
            result = run_autonomous_research_sync(
                mode="fake",
                topic="高寒地区联合救援通信保障能力缺口",
                output_root=root / "runs",
                run_id="reporter-fake",
                max_rounds=2,
                source_whitelist_path=whitelist,
            )
            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            trace_events = [
                json.loads(line)["event_type"]
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            manifest_exists = (result.run_dir / "report_manifest.json").exists()

        self.assertEqual(summary["report"]["report_mode"], "fixture")
        self.assertTrue(summary["report"]["report_context_bundle_id"])
        self.assertIn("report_context_indexed", trace_events)
        self.assertIn("report_context_verified", trace_events)
        self.assertIn("report_published", trace_events)
        self.assertTrue(manifest_exists)


def _whitelist_yaml() -> str:
    return """
version: 1
sources:
  - source_name: Official Source
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [通信, 救援]
    default_queries: ["通信 保障"]
    interaction_profile: static_listing
  - source_name: Journal Source
    source_tier: B
    source_type: journal
    hosts: [journal.example.test]
    fetch_transport: http
    entry_urls: ["https://journal.example.test/CN/"]
    topic_tags: [高寒, 救援]
    default_queries: ["高寒 救援"]
    interaction_profile: static_listing
excluded: []
"""


if __name__ == "__main__":
    unittest.main()
