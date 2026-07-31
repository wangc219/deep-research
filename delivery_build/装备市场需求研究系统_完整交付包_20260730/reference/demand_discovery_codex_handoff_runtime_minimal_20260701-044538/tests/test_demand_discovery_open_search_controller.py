from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.autonomous_research import (  # noqa: E402
    _fixture_judge_provider_factory,
)
from knowledgegraph.demand_discovery.domain.judgement import (  # noqa: E402
    JudgementItem,
    JudgementReport,
)
from knowledgegraph.demand_discovery.domain.models import EvidenceCard, SourceRecord  # noqa: E402
from knowledgegraph.demand_discovery.domain.open_search import (  # noqa: E402
    OpenSearchPlan,
    OpenSourceBodyArtifact,
    OpenSourceLead,
    SourceQualityAssessment,
)
from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry  # noqa: E402
from knowledgegraph.demand_discovery.domain.source_strategy import (  # noqa: E402
    SelectedSource,
    SourceStrategy,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.research_loop import ResearchLoopController  # noqa: E402


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class DemandDiscoveryOpenSearchControllerTests(unittest.TestCase):
    def test_controller_requires_whitelist_round_before_open_search(self) -> None:
        controller = _controller()
        decision = controller._should_trigger_open_search(
            round_index=0,
            judgement=_judgement(_open_plan()),
            new_strong_evidence_count=0,
            consecutive_no_new_sources=1,
            budget_exhausted=False,
        )

        self.assertFalse(decision.should_trigger)
        self.assertEqual(decision.reason, "whitelist_round_required")

    def test_controller_rejects_open_search_when_whitelist_not_exhausted(self) -> None:
        controller = _controller()
        decision = controller._should_trigger_open_search(
            round_index=2,
            judgement=_judgement(_open_plan(whitelist_exhausted=False)),
            new_strong_evidence_count=0,
            consecutive_no_new_sources=1,
            budget_exhausted=False,
        )

        self.assertFalse(decision.should_trigger)
        self.assertEqual(decision.reason, "whitelist_not_exhausted")

    def test_controller_allows_open_search_when_judgement_still_requests_crosscheck(self) -> None:
        controller = _controller()
        decision = controller._should_trigger_open_search(
            round_index=2,
            judgement=_judgement(_open_plan()),
            new_strong_evidence_count=1,
            consecutive_no_new_sources=1,
            budget_exhausted=False,
        )

        self.assertTrue(decision.should_trigger)
        self.assertEqual(decision.reason, "judge_gap_after_whitelist_exhaustion")

    def test_controller_creates_open_search_plan_from_v1_task(self) -> None:
        store = DomainStore()
        controller = _controller(store=store)
        research_round = controller._start_network_round(2, previous_judgement=None)
        judgement = _judgement(
            _open_plan(
                query_revisions=[
                    {"language": "zh", "query": "远海保障 缺口"},
                    {"language": "en", "query": "contested sustainment gap"},
                ]
            )
        )

        plan = controller._maybe_create_open_search_plan(
            round_index=2,
            research_round=research_round,
            judgement=judgement,
            new_strong_evidence_count=0,
            consecutive_no_new_sources=1,
            budget_exhausted=False,
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.status, "planned")
        self.assertIn("远海保障 缺口", plan.queries)
        self.assertIn("contested sustainment gap", plan.queries)
        self.assertIn(plan.plan_id, store.open_search_plans)
        self.assertIn("open_search_plan_created", [event.event_type for event in store.trace_events])

    def test_network_loop_passes_open_search_plan_to_next_round_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = DomainStore()
            controller = _controller(
                store=store,
                max_rounds=2,
                judge_sessions_dir=root / "judge",
            )
            calls: list[dict[str, object]] = []

            async def execute_round(**kwargs):
                calls.append(dict(kwargs))
                domain_path = root / f"{kwargs['round_id']}.jsonl"
                domain_path.write_text("", encoding="utf-8")
                return _WorkerResult(
                    domain_path=domain_path,
                    artifact_dir=root / f"{kwargs['round_id']}-artifacts",
                )

            result = asyncio.run(
                controller.run_network_loop(
                    seed_urls=["https://official.example.test/"],
                    execute_round=execute_round,
                )
            )

        self.assertEqual(len(calls), 2)
        self.assertIs(calls[0]["allow_open_search"], False)
        self.assertEqual(calls[0]["open_search_plan_id"], "")
        self.assertIs(calls[1]["allow_open_search"], True)
        self.assertTrue(str(calls[1]["open_search_plan_id"]).startswith("osp-"))
        self.assertIsInstance(calls[1]["open_search_plan_payload"], dict)
        self.assertTrue(calls[1]["planned_tasks"])
        self.assertEqual(result["open_search_plans"][0]["status"], "completed")
        self.assertEqual(
            result["network_worker_runs"][0]["artifact_dir"],
            str(root / "round-1-artifacts"),
        )
        self.assertEqual(
            result["network_worker_runs"][1]["artifact_dir"],
            str(root / "round-2-artifacts"),
        )
        self.assertIn("open_search_plan", result["trace"])
        trace_events = [event.event_type for event in store.trace_events]
        planned_index = trace_events.index("worker_assignments_planned")
        round2_index = [
            index
            for index, event in enumerate(store.trace_events)
            if event.event_type == "research_round_started"
            and event.target_id == "round-2"
        ][0]
        self.assertLess(planned_index, round2_index)

    def test_default_judge_output_drives_open_search_without_test_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = DomainStore()
            controller = _controller(
                store=store,
                max_rounds=2,
                judge_sessions_dir=root / "judge",
            )
            calls: list[dict[str, object]] = []

            async def execute_round(**kwargs):
                calls.append(dict(kwargs))
                domain_path = root / f"{kwargs['round_id']}.jsonl"
                domain_path.write_text("", encoding="utf-8")
                return _WorkerResult(domain_path=domain_path)

            result = asyncio.run(
                controller.run_network_loop(
                    seed_urls=["https://official.example.test/"],
                    execute_round=execute_round,
                )
            )

        self.assertEqual(len(calls), 2)
        self.assertIs(calls[0]["allow_open_search"], False)
        self.assertIs(calls[1]["allow_open_search"], True)
        self.assertTrue(str(calls[1]["open_search_plan_id"]).startswith("osp-"))
        self.assertEqual(len(result["open_search_plans"]), 1)

    def test_network_loop_does_not_count_weak_evidence_as_new_strong_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = DomainStore()
            store.upsert_source(_whitelist_source())
            controller = _controller(
                store=store,
                max_rounds=2,
                judge_sessions_dir=root / "judge",
            )
            calls: list[dict[str, object]] = []

            async def execute_round(**kwargs):
                calls.append(dict(kwargs))
                domain_path = root / f"{kwargs['round_id']}.jsonl"
                if kwargs["round_id"] == "round-1":
                    worker_store = DomainStore()
                    worker_store.upsert_source(_whitelist_source())
                    worker_store.upsert_evidence(_weak_evidence())
                    worker_store.export_jsonl(domain_path)
                else:
                    domain_path.write_text("", encoding="utf-8")
                return _WorkerResult(domain_path=domain_path)

            result = asyncio.run(
                controller.run_network_loop(
                    seed_urls=["https://official.example.test/"],
                    execute_round=execute_round,
                )
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["round_id"], "round-1")
        self.assertIs(calls[1]["allow_open_search"], True)
        self.assertEqual(len(result["open_search_plans"]), 1)

    def test_network_loop_triggers_open_search_when_new_sources_have_no_strong_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = DomainStore()
            controller = _controller(
                store=store,
                max_rounds=2,
                judge_sessions_dir=root / "judge",
            )
            calls: list[dict[str, object]] = []

            async def execute_round(**kwargs):
                calls.append(dict(kwargs))
                domain_path = root / f"{kwargs['round_id']}.jsonl"
                if kwargs["round_id"] == "round-1":
                    worker_store = DomainStore()
                    worker_store.upsert_source(
                        SourceRecord(
                            source_id="src-new-background",
                            title="Fresh listing or background source",
                            source_name="Official",
                            source_tier="A",
                            source_type="official",
                            publish_time=NOW,
                            url_or_path="https://official.example.test/listing",
                            summary_text="new source without body evidence",
                            summary_source="worker",
                            collection_decision="use_as_background",
                            author_or_org=None,
                            is_repost=False,
                            original_source=None,
                            institutional_stance=None,
                            created_at=NOW,
                            updated_at=NOW,
                        )
                    )
                    worker_store.export_jsonl(domain_path)
                else:
                    domain_path.write_text("", encoding="utf-8")
                return _WorkerResult(domain_path=domain_path)

            result = asyncio.run(
                controller.run_network_loop(
                    seed_urls=["https://official.example.test/"],
                    execute_round=execute_round,
                )
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["round_id"], "round-1")
        self.assertIs(calls[0]["allow_open_search"], False)
        self.assertEqual(calls[1]["round_id"], "round-2")
        self.assertIs(calls[1]["allow_open_search"], True)
        self.assertEqual(len(result["open_search_plans"]), 1)

    def test_network_loop_stops_when_worker_imports_strong_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = DomainStore()
            controller = _controller(
                store=store,
                max_rounds=3,
                judge_sessions_dir=root / "judge",
            )
            calls: list[dict[str, object]] = []

            async def execute_round(**kwargs):
                calls.append(dict(kwargs))
                domain_path = root / f"{kwargs['round_id']}.jsonl"
                worker_store = DomainStore()
                worker_store.upsert_source(_whitelist_source())
                worker_store.upsert_evidence(_strong_evidence())
                worker_store.export_jsonl(domain_path)
                return _WorkerResult(domain_path=domain_path)

            result = asyncio.run(
                controller.run_network_loop(
                    seed_urls=["https://official.example.test/"],
                    execute_round=execute_round,
                )
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["rounds"][0]["status"], "stopped")
        self.assertEqual(result["candidate_synthesis"]["status"], "synthesized")

    def test_network_loop_imports_open_source_lineage_before_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            domain_path = Path(tmp) / "worker-domain.jsonl"
            worker_store = _open_source_worker_store()
            worker_store.export_jsonl(domain_path)
            store = DomainStore()
            controller = _controller(store=store)

            imported = controller._import_network_worker_domain(domain_path)

        self.assertIn("osp-1", store.open_search_plans)
        self.assertIn("osl-1", store.open_source_leads)
        self.assertIn("qa-1", store.source_quality_assessments)
        self.assertIn("src-open", store.sources)
        self.assertIn("ev-open", store.evidence)
        self.assertEqual(imported["new_evidence_ids"], ["ev-open"])


@dataclass
class _WorkerResult:
    domain_path: Path
    artifact_dir: Path | str = ""
    run_id: str = "worker-run"
    run_dir: str = ""
    trace_event_count: int = 0
    report_trace_event_count: int = 0


def _controller(
    *,
    store: DomainStore | None = None,
    max_rounds: int = 3,
    judge_sessions_dir: Path | None = None,
) -> ResearchLoopController:
    source = SelectedSource(
        source_name="Official",
        source_tier="A",
        source_type="official",
        fetch_transport="http",
        entry_urls=["https://official.example.test/"],
        content_languages=["zh"],
        planned_queries=["远海保障"],
        default_queries=["远海保障"],
        interaction_profile="static_listing",
        rationale="test",
    )
    strategy = SourceStrategy(
        strategy_id="strategy-1",
        topic="远海保障能力缺口",
        selected_sources=[source],
        seed_urls=["https://official.example.test/"],
    )
    return ResearchLoopController(
        run_id="run-1",
        topic=strategy.topic,
        strategy=strategy,
        store=store or DomainStore(),
        registry=SourceRegistry(sources=[]),
        max_rounds=max_rounds,
        judge_provider_factory=_fixture_judge_provider_factory(topic=strategy.topic),
        judge_sessions_dir=(
            judge_sessions_dir
            or Path(tempfile.gettempdir()) / "demand-discovery-open-search-judge"
        ),
    )


def _judgement(
    next_round_plan: dict[str, object],
    *,
    judgement_id: str = "judge-1",
) -> JudgementReport:
    return JudgementReport(
        judgement_id=judgement_id,
        round_id="round-1",
        consensus_points=[
            JudgementItem(
                text="已有白名单材料显示保障能力存在覆盖不足",
                worker_report_ids=["worker-1"],
                evidence_ids=["ev-1"],
            )
        ],
        contradictions=[],
        partial_coverage=[],
        unique_insights=[],
        blind_spots=[
            JudgementItem(
                text="缺少开放来源对远海保障组织方式的交叉材料",
                worker_report_ids=["worker-1"],
                lead_ids=["lead-1"],
            )
        ],
        evidence_strength_map={"ev-1": "partial"},
        next_round_plan=next_round_plan,
        stop_or_continue="continue",
        rationale="needs more evidence",
        created_at=NOW,
    )


def _open_plan(
    *,
    whitelist_exhausted: bool = True,
    query_revisions: list[object] | None = None,
) -> dict[str, object]:
    return {
        "plan_version": 1,
        "round_id": "round-1",
        "summary": "白名单证据不足，需要受控开放搜索补证",
        "controller_tasks": [
            {
                "task_id": "task-open-1",
                "objective": "寻找远海保障能力缺口的公开正文交叉材料",
                "gap_type": "missing_direct_evidence",
                "input_refs": {
                    "worker_report_ids": ["worker-1"],
                    "evidence_ids": ["ev-1"],
                    "lead_ids": ["lead-1"],
                },
                "routing_hint": "open_search_candidate",
                "source_scope": (
                    "open_web_after_whitelist_exhausted"
                    if whitelist_exhausted
                    else "open_web"
                ),
                "query_revisions": query_revisions or [{"language": "zh", "query": "远海保障 缺口"}],
                "completion_check": (
                    "白名单 route/query 已耗尽或无新增，开放搜索读取正文"
                    if whitelist_exhausted
                    else "继续白名单 route/query 读取正文"
                ),
            }
        ],
        "worker_briefs": {
            "task-open-1": "优先使用给定 query 寻找远海保障能力缺口公开正文。"
        },
        "remaining_open_questions": ["缺少开放来源交叉材料"],
        "stop_candidate_reason": "",
    }


def _open_source_worker_store() -> DomainStore:
    store = DomainStore()
    store.upsert_open_search_plan(
        OpenSearchPlan(
            plan_id="osp-1",
            run_id="run-1",
            round_id="round-1",
            topic="远海保障能力缺口",
            trigger_judgement_id="judge-1",
            trigger_reason="白名单 route/query 已耗尽",
            queries=["远海保障 缺口"],
            allowed_result_count=3,
            status="running",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_open_source_lead(
        OpenSourceLead(
            lead_id="osl-1",
            plan_id="osp-1",
            run_id="run-1",
            round_id="round-1",
            topic="远海保障能力缺口",
            url="https://open.example.test/report",
            domain="open.example.test",
            title="Open report",
            snippet="远海保障公开正文",
            source_name_guess="Open Example",
            search_query="远海保障 缺口",
            source_scope="open_web",
            quality_status="pending",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_open_source_body_artifact(
        OpenSourceBodyArtifact(
            body_id="osb-1",
            lead_id="osl-1",
            plan_id="osp-1",
            url="https://open.example.test/report",
            final_url="https://open.example.test/report",
            content_type="text/html",
            artifact_ref="html:open",
            simplified_ref="text:open",
            body_location_prefix="text:open#para:",
            fetched_by="worker",
            created_at=NOW,
        )
    )
    store.upsert_source_quality_assessment(
        SourceQualityAssessment(
            assessment_id="qa-1",
            lead_id="osl-1",
            url="https://open.example.test/report",
            domain="open.example.test",
            basis_artifact_refs=["text:open"],
            body_location_refs=["text:open#para:0"],
            read_document_ref="text:open",
            source_identity="Open Example",
            publisher_or_org="Open Example",
            author="",
            publish_time="2026-06-20",
            is_original_source=True,
            citation_or_reference_signal="public report",
            content_type="article",
            quality_level="usable",
            risk_flags=[],
            reason="正文和发布主体可核验",
            created_by="worker",
            created_at=NOW,
        )
    )
    store.upsert_source(
        SourceRecord(
            source_id="src-open",
            title="Open report",
            source_name="Open Example",
            source_tier="B",
            source_type="open_web",
            publish_time=NOW,
            url_or_path="https://open.example.test/report",
            summary_text="公开正文",
            summary_source="worker",
            collection_decision="use_as_evidence",
            author_or_org=None,
            is_repost=False,
            original_source=None,
            institutional_stance=None,
            created_at=NOW,
            updated_at=NOW,
            open_source_lead_id="osl-1",
        )
    )
    store.upsert_evidence(
        EvidenceCard(
            evidence_id="ev-open",
            source_id="src-open",
            claim="远海保障存在持续维护能力缺口",
            evidence_summary="公开正文支持远海保障缺口判断",
            excerpt="远海保障需要持续维护能力。",
            source_location="text:open#para:0",
            evidence_assessment="strong",
            created_by="worker",
            created_at=NOW,
            source_quality_assessment_id="qa-1",
        )
    )
    return store


def _whitelist_source() -> SourceRecord:
    return SourceRecord(
        source_id="src-whitelist",
        title="Official article",
        source_name="Official",
        source_tier="A",
        source_type="official",
        publish_time=NOW,
        url_or_path="https://official.example.test/article",
        summary_text="white-list article",
        summary_source="worker",
        collection_decision="use_as_evidence",
        author_or_org=None,
        is_repost=False,
        original_source=None,
        institutional_stance=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _weak_evidence() -> EvidenceCard:
    return EvidenceCard(
        evidence_id="ev-weak",
        source_id="src-whitelist",
        claim="远海保障能力缺口仍需补证",
        evidence_summary="正文只提供背景描述，尚不足以支撑强结论",
        excerpt="远海保障仍需结合更多公开材料判断。",
        source_location="text:official#para:0",
        evidence_assessment="weak",
        created_by="worker",
        created_at=NOW,
    )


def _strong_evidence() -> EvidenceCard:
    return EvidenceCard(
        evidence_id="ev-strong",
        source_id="src-whitelist",
        claim="远海保障存在持续维护能力缺口",
        evidence_summary="正文直接支持远海保障能力缺口判断",
        excerpt="远海保障需要持续维护能力。",
        source_location="text:official#para:0",
        evidence_assessment="strong",
        created_by="worker",
        created_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
