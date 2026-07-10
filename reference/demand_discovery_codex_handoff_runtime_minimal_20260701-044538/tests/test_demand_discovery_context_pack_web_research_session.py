from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.context_pack import ContextPackBuilder  # noqa: E402


class ContextPackWebResearchSessionTests(unittest.TestCase):
    def test_context_pack_renders_compact_session_without_full_html(self) -> None:
        pack = ContextPackBuilder().build(
            agent_role="reading_worker",
            task_brief="调查极地通信保障能力缺口",
            run_state={
                "web_research_sessions": [
                    {
                        "session_id": "wrs-1",
                        "assignment_id": "assignment-1",
                        "status": "running",
                        "active_acceptance_criteria": [],
                        "allowed_source_refs": ["source:example"],
                        "recent_refs": [
                            {
                                "type": "ResearchLead",
                                "id": "lead-1",
                                "summary": "candidate only search result",
                                "quality": "candidate_only",
                            },
                            {
                                "type": "tool_result",
                                "id": "js-result-1",
                                "summary": "JS API candidate, not evidence",
                                "quality": "not_evidence",
                            },
                        ],
                        "compact_summaries": ["搜索页只给出候选，不是正文证据。"],
                        "attempted_routes": [
                            {"route": "site_search", "outcome": "listing_only"}
                        ],
                        "open_questions": ["缺少正文证据"],
                        "last_self_check_ref": "selfcheck-1",
                        "follow_up_refs": ["followup-1"],
                        "blocked_reasons": [],
                    }
                ],
                "documents": [
                    {
                        "artifact_ref": "html:full",
                        "title": "full html",
                        "text": "<html><body>" + ("x" * 1000) + "</body></html>",
                    }
                ],
            },
            token_budget=1200,
        )

        rendered = pack.render()
        self.assertIn("web_research_sessions", rendered)
        self.assertIn("active_acceptance_criteria", rendered)
        self.assertIn("allowed_source_refs", rendered)
        self.assertIn("recent_refs", rendered)
        self.assertIn("compact_summaries", rendered)
        self.assertIn("attempted_routes", rendered)
        self.assertIn("last_self_check_ref", rendered)
        self.assertIn("follow_up_refs", rendered)
        self.assertIn("candidate_only", rendered)
        self.assertIn("not_evidence", rendered)
        self.assertIn("[]", rendered)
        self.assertNotIn("<html", rendered.lower())
        self.assertNotIn("x" * 200, rendered)


if __name__ == "__main__":
    unittest.main()
