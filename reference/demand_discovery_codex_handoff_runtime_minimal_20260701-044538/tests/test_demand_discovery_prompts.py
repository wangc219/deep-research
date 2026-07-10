from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.workers.agent_defs import (  # noqa: E402
    default_agent_dir,
    discover_agents,
)
from knowledgegraph.demand_discovery.workers.prompts import (  # noqa: E402
    render_system_prompt,
)


class DemandDiscoveryPromptTests(unittest.TestCase):
    def test_phase2_agents_are_discoverable_and_contain_required_disciplines(self) -> None:
        agents = discover_agents(default_agent_dir())

        self.assertIn("orchestrator", agents)
        self.assertIn("reader", agents)
        self.assertIn("auditor", agents)
        self.assertIn("debater", agents)
        self.assertIn("objective", agents["orchestrator"].system_prompt)
        self.assertIn("findings", agents["reader"].system_prompt)
        self.assertIn("scorecard", agents["auditor"].system_prompt)
        self.assertIn("does not decide pass or fail", agents["debater"].system_prompt)

    def test_render_system_prompt_injects_run_context(self) -> None:
        agents = discover_agents(default_agent_dir())

        rendered = render_system_prompt(
            agents["reader"],
            {
                "run_id": "run-1",
                "date": "2026-06-11",
                "source_registry_summary": "A-tier only",
            },
        )

        self.assertIn("run-1", rendered)
        self.assertIn("2026-06-11", rendered)
        self.assertIn("A-tier only", rendered)

    def test_reader_prompt_defines_whitelist_exhaustion_and_handoff_sop(self) -> None:
        agents = discover_agents(default_agent_dir())
        prompt = agents["reader"].system_prompt

        for phrase in [
            "Whitelist-First Research",
            "Whitelist Exhaustion Check",
            "Open Search Mode",
            "evidence_ready_for_judge",
            "stop_reason",
            "whitelist_exhausted",
            "needs_open_search",
            "open_source_lead_id",
            "need_more_sources=true",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_judge_prompt_defines_semantic_planning_and_stop_sop(self) -> None:
        agents = discover_agents(default_agent_dir())
        prompt = agents["judge"].system_prompt

        for phrase in [
            "Judge / Research Planning Agent",
            "semantic judge",
            "Check Worker Output Quality",
            "Decide Stop Or Continue",
            "Open Search Decision",
            "Stop For Report",
            "stop_for_report",
            "Do not continue only because open questions exist",
            "Every executable controller task must include non-empty `input_refs.worker_report_ids`",
            "Call `record_judgement` exactly once",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_auditor_prompt_defines_evidence_support_audit_sop(self) -> None:
        agents = discover_agents(default_agent_dir())
        prompt = agents["auditor"].system_prompt

        for phrase in [
            "Auditor / Evidence Support Review Agent",
            "evidence-support audit agent",
            "Read The Audit Bundle",
            "Decompose Core Claims",
            "Review Evidence Support",
            "Source Quality Rules",
            "Decide Report Status",
            "Audit not passing is a normal business outcome",
            "Do not perform multi-round research",
            "Call `run_audit` exactly once",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_reporter_prompt_defines_human_readable_report_sop(self) -> None:
        agents = discover_agents(default_agent_dir())
        prompt = agents["reporter"].system_prompt

        for phrase in [
            "Reporter / Final Report Writing Agent",
            "human-readable Chinese report",
            "Read The Verified ReportContextBundle",
            "Write A Human-Readable Chinese Report",
            "Adjust Wording By Audit Status",
            "review_ready",
            "needs_revision",
            "watchlist",
            "rejected",
            "Respect Allowed And Blocked Boundaries",
            "Use expand_report_context Carefully",
            "Call generate_demand_report exactly once",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_context_curator_prompt_defines_report_context_curation_sop(self) -> None:
        agents = discover_agents(default_agent_dir())
        prompt = agents["context_curator"].system_prompt

        for phrase in [
            "Context Curator / Report Context Curation Agent",
            "report-context material curator",
            "Read The ReportContextCandidatePool",
            "Select, Merge, Or Exclude Materials",
            "Respect Allowed Report Uses",
            "Preserve Audit Caveats And Blocked Claims",
            "Do Not Continue Research",
            "Do not search, fetch pages, read new documents, create EvidenceCard",
            "Call record_report_context_curation exactly once",
            "No Usable Core Evidence",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)


if __name__ == "__main__":
    unittest.main()
