from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import EvidenceCard, SourceRecord  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.web_research_session import WebResearchSession  # noqa: E402
from knowledgegraph.demand_discovery.harness.agent_harness import ApparentStopContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.worker_stop_policy import (  # noqa: E402
    WorkerStopPolicy,
    WorkerStopPolicyConfig,
)


class WorkerStopPolicyTests(unittest.TestCase):
    def test_returns_follow_up_when_body_evidence_is_missing(self) -> None:
        store = DomainStore()
        policy = _policy(store)

        decision = policy.evaluate()

        self.assertFalse(decision.allow_stop)
        self.assertIsNotNone(decision.self_check)
        self.assertIsNotNone(decision.follow_up_instruction)
        self.assertEqual(decision.blocked_reason, "body_evidence_missing")
        self.assertEqual(policy.follow_up_attempt_count, 1)
        self.assertIn("正文", decision.follow_up_instruction.to_prompt())
        self.assertIn(
            "worker_self_check_recorded",
            [event.event_type for event in store.trace_events],
        )
        self.assertIn(
            "worker_follow_up_planned",
            [event.event_type for event in store.trace_events],
        )

    def test_allows_stop_when_direct_body_evidence_exists(self) -> None:
        store = _store_with_evidence_fixture(
            assignment_id="assignment-1",
            source_location="artifact:article-1#p1",
            evidence_assessment="direct",
            artifact_refs=["artifact:article-1"],
        )
        decision = _policy(store).evaluate()

        self.assertTrue(decision.allow_stop)
        self.assertIsNone(decision.follow_up_instruction)
        self.assertEqual(decision.self_check.follow_up_reason, "")

    def test_rejects_listing_or_foreign_assignment_evidence(self) -> None:
        listing_decision = _policy(
            _store_with_evidence_fixture(
                assignment_id="assignment-1",
                source_location="listing:https://example.test/search?q=topic",
                evidence_assessment="direct",
                artifact_refs=[],
            )
        ).evaluate()
        self.assertFalse(listing_decision.allow_stop)
        self.assertEqual(listing_decision.blocked_reason, "body_evidence_missing")

        foreign_decision = _policy(
            _store_with_evidence_fixture(
                assignment_id="other-assignment",
                source_location="artifact:article-foreign#p1",
                evidence_assessment="direct",
                artifact_refs=["artifact:article-foreign"],
            )
        ).evaluate()
        self.assertFalse(foreign_decision.allow_stop)
        self.assertEqual(foreign_decision.blocked_reason, "body_evidence_missing")

    def test_two_partial_cards_from_same_artifact_do_not_pass(self) -> None:
        decision = _policy(_store_with_two_partial_evidence_cards_same_artifact()).evaluate()

        self.assertFalse(decision.allow_stop)
        self.assertEqual(decision.blocked_reason, "direct_evidence_missing")

    def test_repeated_injection_without_new_body_artifact_blocks(self) -> None:
        store = DomainStore()
        policy = _policy(store, max_follow_ups=2)
        ctx = ApparentStopContext(
            last_assistant_text="findings:\n- 没有正文",
            budget_state="normal",
            follow_up_attempt_count=0,
            recent_domain_delta={"open_source_body_artifacts": 0, "body_artifact_refs": 0},
            recent_trace_events=[],
            repeated_injection_keys=set(),
        )

        first = policy.apparent_stop_follow_up_policy(ctx)
        second = policy.apparent_stop_follow_up_policy(
            ApparentStopContext(
                last_assistant_text="findings:\n- 仍没有正文",
                budget_state="normal",
                follow_up_attempt_count=1,
                recent_domain_delta={
                    "open_source_body_artifacts": 0,
                    "body_artifact_refs": 0,
                },
                recent_trace_events=[],
                repeated_injection_keys=set(policy.recent_injection_keys),
            )
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertIn(
            "worker_blocked",
            [event.event_type for event in store.trace_events],
        )

    def test_wrapping_up_budget_does_not_inject_follow_up(self) -> None:
        store = DomainStore()
        policy = _policy(store)

        texts = policy.apparent_stop_follow_up_policy(
            ApparentStopContext(
                last_assistant_text="findings:\n- 没有正文",
                budget_state="wrapping_up",
                follow_up_attempt_count=0,
                recent_domain_delta={},
                recent_trace_events=[],
                repeated_injection_keys=set(),
            )
        )

        self.assertEqual(texts, [])
        self.assertIn("worker_blocked", [event.event_type for event in store.trace_events])


def _policy(store: DomainStore, *, max_follow_ups: int = 2) -> WorkerStopPolicy:
    return WorkerStopPolicy(
        store=store,
        config=WorkerStopPolicyConfig(
            run_id="run-1",
            round_id="round-1",
            assignment_id="assignment-1",
            source_id="source-a",
            allowed_tools=["search_sources", "fetch_page", "read_document"],
            query_revisions=[{"language": "auto", "query": "极地通信保障 能力缺口"}],
            route_revisions=["站内搜索"],
            max_follow_ups_per_assignment=max_follow_ups,
        ),
    )


def _store_with_evidence_fixture(
    *,
    assignment_id: str,
    source_location: str,
    evidence_assessment: str,
    artifact_refs: list[str],
) -> DomainStore:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = DomainStore()
    store.upsert_source(_source_record(now))
    store.upsert_evidence(
        EvidenceCard(
            evidence_id="ev-1",
            source_id="source-a",
            claim="测试 claim",
            evidence_summary="测试 evidence",
            excerpt="短摘录",
            source_location=source_location,
            evidence_assessment=evidence_assessment,
            created_by="reader",
            created_at=now,
        )
    )
    store.upsert_web_research_session(
        WebResearchSession(
            session_id=f"wrs-{assignment_id}",
            assignment_id=assignment_id,
            round_id="round-1",
            runtime_ref=f"agent-{assignment_id}",
            topic_snapshot="极地通信保障能力缺口",
            status="running",
            active_acceptance_criteria=["至少读取一篇正文"],
            allowed_source_refs=["source:source-a"],
            recent_refs=[
                {"type": "artifact", "id": ref, "location_ref": f"{ref}#p1"}
                for ref in artifact_refs
            ]
            + [{"type": "EvidenceCard", "id": "ev-1"}],
            attempted_routes=[
                {
                    "route": "read_document" if artifact_refs else "listing_page",
                    "outcome": "body_artifact_read" if artifact_refs else "listing_only",
                    "output_refs": [*artifact_refs, "ev-1"],
                }
            ],
        )
    )
    return store


def _store_with_two_partial_evidence_cards_same_artifact() -> DomainStore:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = DomainStore()
    store.upsert_source(_source_record(now))
    for index in range(2):
        store.upsert_evidence(
            EvidenceCard(
                evidence_id=f"ev-partial-{index}",
                source_id="source-a",
                claim=f"partial claim {index}",
                evidence_summary="同一正文 artifact 的部分支撑",
                excerpt="短摘录",
                source_location=f"artifact:article-1#p{index + 1}",
                evidence_assessment="partial",
                created_by="reader",
                created_at=now,
            )
        )
    store.upsert_web_research_session(
        WebResearchSession(
            session_id="wrs-1",
            assignment_id="assignment-1",
            round_id="round-1",
            runtime_ref="agent-1",
            topic_snapshot="极地通信保障能力缺口",
            status="running",
            active_acceptance_criteria=["需要 direct 或两个不同正文 artifact 的 partial"],
            allowed_source_refs=["source:source-a"],
            recent_refs=[
                {"type": "artifact", "id": "artifact:article-1", "location_ref": "artifact:article-1#p1"},
                {"type": "EvidenceCard", "id": "ev-partial-0"},
                {"type": "EvidenceCard", "id": "ev-partial-1"},
            ],
            attempted_routes=[
                {
                    "route": "read_document",
                    "outcome": "same_artifact_partial_only",
                    "output_refs": ["artifact:article-1", "ev-partial-0", "ev-partial-1"],
                }
            ],
        )
    )
    return store


def _source_record(now: datetime) -> SourceRecord:
    return SourceRecord(
        source_id="source-a",
        title="极地通信保障报道",
        source_name="Source A",
        source_tier="B",
        source_type="article",
        publish_time=now,
        url_or_path="https://example.test/article.html",
        summary_text="正文摘要",
        summary_source="read_document",
        collection_decision="selected",
        author_or_org="Example",
        is_repost=False,
        original_source=None,
        institutional_stance=None,
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
