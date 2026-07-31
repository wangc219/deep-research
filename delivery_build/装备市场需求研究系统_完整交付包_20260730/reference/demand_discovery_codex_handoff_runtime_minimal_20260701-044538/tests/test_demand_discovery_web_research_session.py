from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.web_research_session import (  # noqa: E402
    WebResearchSession,
    web_research_session_from_dict,
)


def _session() -> WebResearchSession:
    return WebResearchSession(
        session_id="wrs-1",
        assignment_id="assignment-1",
        round_id="round-1",
        runtime_ref="agent-1",
        topic_snapshot="极地通信保障能力缺口",
        status="running",
        active_acceptance_criteria=["至少读取一篇正文", "strong finding 必须引用 evidence refs"],
        allowed_source_refs=["source:81-cn", "open_search_plan:osp-1"],
        recent_refs=[
            {"type": "ResearchLead", "id": "lead-1", "summary": "站内搜索候选"},
            {
                "type": "artifact",
                "id": "artifact:article-1",
                "location_ref": "artifact:article-1#p1",
                "summary": "正文 partial 支撑",
            },
        ],
        compact_summaries=[
            "query=极地 通信保障 能力缺口；读取 artifact:article-1；只有 partial 支撑。"
        ],
        attempted_routes=[
            {
                "route": "source_search",
                "query": "极地 通信保障 能力缺口",
                "outcome": "partial_body_read",
                "output_refs": ["lead-1", "artifact:article-1"],
            }
        ],
        open_questions=["仍缺少直接讨论能力缺口的第二来源正文"],
        last_self_check_ref="selfcheck-1",
        follow_up_refs=["followup-1"],
        blocked_reasons=[],
    )


class WebResearchSessionTests(unittest.TestCase):
    def test_rejects_unknown_status_and_invalid_refs(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown WebResearchSession status"):
            WebResearchSession(
                session_id="wrs-1",
                assignment_id="assignment-1",
                round_id="round-1",
                runtime_ref="agent-1",
                topic_snapshot="topic",
                status="done",
            )

        with self.assertRaisesRegex(ValueError, "recent_refs item requires type and id"):
            WebResearchSession(
                session_id="wrs-1",
                assignment_id="assignment-1",
                round_id="round-1",
                runtime_ref="agent-1",
                topic_snapshot="topic",
                status="running",
                recent_refs=[{"type": "artifact", "summary": "missing id"}],
            )

    def test_rejects_full_html_in_compact_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not store full HTML"):
            WebResearchSession(
                session_id="wrs-1",
                assignment_id="assignment-1",
                round_id="round-1",
                runtime_ref="agent-1",
                topic_snapshot="topic",
                status="running",
                compact_summaries=["<html><body>secret full page</body></html>"],
            )

    def test_dict_round_trip(self) -> None:
        session = _session()
        self.assertEqual(
            web_research_session_from_dict(session.to_dict()).to_dict(),
            session.to_dict(),
        )

    def test_domain_store_round_trip_covers_export_append_load_and_apply(self) -> None:
        session = _session()
        with tempfile.TemporaryDirectory() as tmp:
            export_path = Path(tmp) / "domain-export.jsonl"
            append_path = Path(tmp) / "domain-append.jsonl"

            store = DomainStore()
            store.upsert_web_research_session(session)
            store.export_jsonl(export_path)
            loaded_export = DomainStore.load_jsonl(export_path)

            store.export_append_only_snapshot(append_path)
            loaded_append = DomainStore.load_jsonl(append_path)

        self.assertEqual(
            loaded_export.web_research_sessions["wrs-1"].to_dict(),
            session.to_dict(),
        )
        self.assertEqual(
            loaded_append.web_research_sessions["wrs-1"].to_dict(),
            session.to_dict(),
        )

    def test_store_does_not_create_second_workflow_database(self) -> None:
        store = DomainStore()
        self.assertTrue(hasattr(store, "web_research_sessions"))
        for name in [
            "search_result_candidates",
            "opened_research_pages",
            "research_body_spans",
            "source_decisions",
            "evidence_candidates",
            "research_next_actions",
        ]:
            self.assertFalse(hasattr(store, name), name)


if __name__ == "__main__":
    unittest.main()
