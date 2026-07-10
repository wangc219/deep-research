from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery import network_research as network_research_module  # noqa: E402
from knowledgegraph.demand_discovery.domain.open_search import OpenSearchPlan  # noqa: E402
from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import AssistantContentBlock, ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse  # noqa: E402
from knowledgegraph.demand_discovery.llm.types import AssistantMessage  # noqa: E402
from knowledgegraph.demand_discovery.network_research import _real_provider  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.documents import create_read_document_tool  # noqa: E402
from knowledgegraph.demand_discovery.tools.network import HttpFetchResponse  # noqa: E402
from knowledgegraph.demand_discovery.tools.open_fetch import create_fetch_open_source_page_tool  # noqa: E402
from knowledgegraph.demand_discovery.tools.search import (  # noqa: E402
    OpenSearchHit,
    StaticOpenSearchAdapter,
    create_open_search_sources_tool,
)


class DemandDiscoveryNetworkResearchRunnerTests(unittest.TestCase):
    def test_worker_round_loads_reader_role_prompt_into_provider_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            provider = FakeProvider()

            def assert_reader_prompt(context, state):
                del state
                for phrase in [
                    "Reader / Network Research Worker",
                    "Whitelist Exhaustion Check",
                    "Open Search Mode",
                    "evidence_ready_for_judge",
                    "need_more_sources",
                ]:
                    if phrase not in context.system_prompt:
                        raise AssertionError(f"missing reader prompt phrase: {phrase}")
                return AssistantMessage(
                    content=[
                        AssistantContentBlock(
                            type="text",
                            text=(
                                "findings:\n- none\n\n"
                                "evidence_ready_for_judge: false\n\n"
                                "stop_reason:\n- whitelist_exhausted\n\n"
                                "remaining_gaps:\n- none\n\n"
                                "suggested_next_routes:\n- none\n\n"
                                "need_more_sources: true\n\n"
                                "risks:\n- none"
                            ),
                        )
                    ]
                )

            provider.set_responses([FakeResponse(factory=assert_reader_prompt)])

            with patch.object(
                network_research_module,
                "_fake_worker_round_provider",
                return_value=provider,
            ):
                result = network_research_module.run_network_worker_round_sync(
                    mode="fake",
                    topic="低空无人机探测预警能力缺口",
                    seed_urls=["https://example.test/report"],
                    output_root=root / "runs",
                    run_id="network-worker-reader-prompt",
                    round_id="round-1",
                    source_whitelist_path=whitelist,
                    http_transport=_fixture_transport,
                )

        self.assertEqual(result.error, "")
        self.assertEqual(provider.pending_count(), 0)

    def test_phase5_worker_round_brief_separates_search_language_and_chinese_analysis(self) -> None:
        brief = network_research_module._worker_round_brief(
            "高寒地区联合救援保障能力缺口",
            ["https://relief.example.test/"],
            "round-1",
            source_guidance=[
                {
                    "source_name": "English Relief Source",
                    "url": "https://relief.example.test/",
                    "content_languages": ["en"],
                    "planned_queries": [
                        "cold regions joint rescue support capability gap"
                    ],
                }
            ],
        )

        self.assertIn("English-language sites in English", brief)
        self.assertIn("target site's language", brief)
        self.assertIn("EvidenceCard.claim", brief)
        self.assertIn("write analytic outputs in Chinese", brief)

    def test_open_search_brief_uses_provider_then_browser_fallback_not_google_anchor(self) -> None:
        brief = network_research_module._open_search_brief(
            allow_open_search=True,
            open_search_plan_id="osp-1",
            open_search_queries=["低空无人机 防护 能力缺口"],
            allow_browser=True,
        )

        self.assertIn("open_search_sources_batch", brief)
        self.assertIn("open_search_sources", brief)
        self.assertIn("provider-backed", brief)
        self.assertIn("browser_observe", brief)
        self.assertIn("fetch_open_source_page", brief)
        self.assertNotIn("Google Search browser anchor", brief)
        self.assertNotIn("google.com/search", brief)

    def test_open_search_tavily_like_hit_can_fetch_and_read_open_web_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            registry = SourceRegistry.load(whitelist)
            store = DomainStore(tier_status_cap=registry.tier_status_cap)
            now = datetime.now(timezone.utc)
            plan = OpenSearchPlan(
                plan_id="osp-fixture",
                run_id="run-fixture",
                round_id="round-1",
                topic="低空无人机防护能力缺口",
                trigger_judgement_id="judge-1",
                trigger_reason="fixture open search",
                queries=["低空无人机 防护 能力缺口"],
                allowed_result_count=2,
                status="planned",
                created_at=now,
                updated_at=now,
            )
            store.upsert_open_search_plan(plan)
            adapter = StaticOpenSearchAdapter(
                [
                    OpenSearchHit(
                        title="开放报告",
                        url="https://open-web.test/report",
                        snippet="低空无人机防护能力缺口正文线索",
                        source_domain="open-web.test",
                        search_provider="tavily",
                        query_used=plan.queries[0],
                    )
                ]
            )
            search_tool = create_open_search_sources_tool(
                store,
                registry,
                adapters=[adapter],
            )
            ctx = ToolExecutionContext("run-fixture", "agent-1", "reader", {})
            search_result = asyncio.run(
                search_tool.execute(
                    ToolCall(
                        "call-search",
                        "open_search_sources",
                        {
                            "open_search_plan_id": plan.plan_id,
                            "query": plan.queries[0],
                            "top_k": 1,
                        },
                    ),
                    ctx,
                )
            )
            for proposal in search_result.domain_proposals:
                store.apply_domain_proposal(proposal)
            lead_id = search_result.details["open_source_lead_ids"][0]

            async def transport(
                url: str,
                timeout_ms: int,
                max_bytes: int,
            ) -> HttpFetchResponse:
                return HttpFetchResponse(
                    url=url,
                    status_code=200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    content=(
                        "<html><body><article><h1>开放正文</h1>"
                        "<p>低空无人机防护能力存在探测、识别与协同处置短板。</p>"
                        "</article></body></html>"
                    ).encode("utf-8"),
                )

            artifacts = ArtifactStore(root / "artifacts")
            fetch_tool = create_fetch_open_source_page_tool(
                store,
                artifacts,
                http_transport=transport,
            )
            fetch_result = asyncio.run(
                fetch_tool.execute(
                    ToolCall(
                        "call-fetch",
                        "fetch_open_source_page",
                        {
                            "open_search_plan_id": plan.plan_id,
                            "open_source_lead_id": lead_id,
                            "url": "https://open-web.test/report",
                        },
                    ),
                    ctx,
                )
            )
            for proposal in fetch_result.domain_proposals:
                store.apply_domain_proposal(proposal)
            read_tool = create_read_document_tool(artifacts)
            read_result = asyncio.run(
                read_tool.execute(
                    ToolCall(
                        "call-read",
                        "read_document",
                        {
                            "artifact_ref": fetch_result.details["simplified_ref"],
                            "limit": 5,
                        },
                    ),
                    ctx,
                )
            )

        self.assertFalse(search_result.is_error)
        self.assertEqual(search_result.details["open_source_lead_ids"], [lead_id])
        self.assertFalse(fetch_result.is_error)
        self.assertEqual(fetch_result.details["content_type"], "text/html; charset=utf-8")
        self.assertIn(lead_id, store.open_source_leads)
        self.assertTrue(store.open_source_body_artifacts)
        self.assertFalse(read_result.is_error)
        self.assertIn("source_location:", read_result.content)
        self.assertIn("低空无人机防护能力", read_result.content)

    def test_allow_browser_reaches_worker_tool_surface_and_run_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            original_build_all_tools = network_research_module.build_all_tools
            browser_flags: list[bool] = []

            def capturing_build_all_tools(*args, **kwargs):
                browser_flags.append(bool(kwargs.get("enable_browser_tools", False)))
                return original_build_all_tools(*args, **kwargs)

            with patch.object(
                network_research_module,
                "build_all_tools",
                side_effect=capturing_build_all_tools,
            ):
                result = network_research_module.run_network_worker_round_sync(
                    mode="fake",
                    topic="低空无人机探测预警能力缺口",
                    seed_urls=["https://example.test/report"],
                    output_root=root / "runs",
                    run_id="network-worker-browser",
                    round_id="round-1",
                    source_whitelist_path=whitelist,
                    http_transport=_fixture_transport,
                    allow_browser=True,
                )

            run_config = json.loads((result.run_dir / "run_config.json").read_text(encoding="utf-8"))

        self.assertIn(True, browser_flags)
        self.assertIs(run_config["allow_browser"], True)

    def test_real_provider_keeps_transient_retry_enabled(self) -> None:
        provider = _real_provider(
            api_key="test-api-key",
            api_key_env="DD_TEST_KEY",
            endpoint_mode="responses_compatible",
            base_url="https://api.example.test",
            endpoint_path="",
            model="gpt-test",
        )

        self.assertGreaterEqual(provider._config.max_retries, 2)

    def test_worker_round_exports_evidence_without_candidate_audit_or_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            result = network_research_module.run_network_worker_round_sync(
                mode="fake",
                topic="低空无人机探测预警能力缺口",
                seed_urls=["https://example.test/report"],
                output_root=root / "runs",
                run_id="network-worker",
                round_id="round-1",
                source_whitelist_path=whitelist,
                http_transport=_fixture_transport,
                allow_browser=True,
            )

            rows = [
                json.loads(line)
                for line in result.domain_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            row_types = {row["type"] for row in rows}
            run_config = json.loads((result.run_dir / "run_config.json").read_text(encoding="utf-8"))

        self.assertIn("SourceRecord", row_types)
        self.assertIn("EvidenceCard", row_types)
        self.assertNotIn("CandidateDemand", row_types)
        self.assertNotIn("AuditReport", row_types)
        self.assertNotIn("DemandReport", row_types)
        self.assertEqual(result.report_trace_event_count, 0)
        self.assertEqual(result.evidence_ids, ["ev-network-worker-1"])
        self.assertIs(run_config["allow_browser"], True)

    def test_worker_round_enables_open_search_tools_when_plan_is_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            captured: list[dict[str, object]] = []
            original_build_all_tools = network_research_module.build_all_tools

            def capturing_build_all_tools(*args, **kwargs):
                captured.append(
                    {
                        "enable_open_search_tools": kwargs.get(
                            "enable_open_search_tools", False
                        ),
                        "adapter_count": len(kwargs.get("open_search_adapters") or []),
                    }
                )
                return original_build_all_tools(*args, **kwargs)

            open_search_plan = OpenSearchPlan(
                plan_id="osp-worker",
                run_id="run-1",
                round_id="round-1",
                topic="远海保障能力缺口",
                trigger_judgement_id="judge-1",
                trigger_reason="白名单 route/query 已耗尽",
                queries=["远海保障 缺口"],
                allowed_result_count=3,
                status="running",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            adapters = [
                StaticOpenSearchAdapter(
                    [
                        OpenSearchHit(
                            title="开放来源报告",
                            url="https://open.example.test/report",
                            snippet="远海保障缺口公开材料",
                            source_domain="open.example.test",
                            search_provider="fixture",
                            query_used="远海保障 缺口",
                        )
                    ]
                )
            ]

            with patch.object(
                network_research_module,
                "build_all_tools",
                side_effect=capturing_build_all_tools,
            ):
                result = network_research_module.run_network_worker_round_sync(
                    mode="fake",
                    topic="远海保障能力缺口",
                    seed_urls=["https://example.test/report"],
                    output_root=root / "runs",
                    run_id="network-worker-open-search",
                    round_id="round-1",
                    source_whitelist_path=whitelist,
                    http_transport=_fixture_transport,
                    allow_open_search=True,
                    open_search_plan_id="osp-worker",
                    open_search_plan_payload=open_search_plan.to_dict(),
                    open_search_adapters=adapters,
                )

            run_config = json.loads((result.run_dir / "run_config.json").read_text(encoding="utf-8"))
            row_types = {
                json.loads(line)["type"]
                for line in result.domain_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }

        self.assertIn(True, [item["enable_open_search_tools"] for item in captured])
        self.assertIn(1, [item["adapter_count"] for item in captured])
        self.assertIs(run_config["allow_open_search"], True)
        self.assertEqual(run_config["open_search_plan_id"], "osp-worker")
        self.assertIn("OpenSearchPlan", row_types)


def _write_whitelist(root: Path) -> Path:
    whitelist = root / "source_whitelist.yaml"
    whitelist.write_text(
        """
version: 1
sources:
  - source_name: Fixture Source
    source_tier: A
    source_type: official
    hosts: [example.test]
    fetch_transport: http
    search: {type: none}
    rate_limit_ms: 0
excluded: []
""",
        encoding="utf-8",
    )
    return whitelist


async def _fixture_transport(
    url: str,
    timeout_ms: int,
    max_bytes: int,
) -> HttpFetchResponse:
    return HttpFetchResponse(
        url=url,
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=(
            "<html><body><article><h1>低空探测需求</h1>"
            "<p>复杂环境下低空无人机探测预警能力需求仍有短板。</p>"
            "<p>需要融合多源探测和快速告警能力。</p>"
            "</article></body></html>"
        ).encode("utf-8"),
    )


if __name__ == "__main__":
    unittest.main()
