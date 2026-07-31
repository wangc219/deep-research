from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.source_registry import (  # noqa: E402
    SourceRegistry,
    WhitelistEntry,
)
from knowledgegraph.demand_discovery.domain.source_health import (  # noqa: E402
    SourceHealthSnapshot,
    SourceHealthStatus,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import build_all_tools  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.acquisition import (  # noqa: E402
    AcquiredDocument,
    AcquiredDocumentStore,
    AcquisitionAdapterResult,
    EntryUrlProbeAdapter,
    SourceAcquisitionAdapter,
    SourceAcquisitionRequest,
    create_acquire_whitelist_documents_tool,
    create_read_acquired_document_tool,
)
from knowledgegraph.demand_discovery.tools.acquisition_adapters import (  # noqa: E402
    MlplaJournalAdapter,
)
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.network import HttpFetchResponse  # noqa: E402


class DemandDiscoveryAcquisitionToolTests(unittest.TestCase):
    def test_acquire_whitelist_documents_accepts_query_bundle_and_fans_out_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = SourceRegistry([_entry("Source A", "a.example.test")])
            adapter = _RecordingAdapter(
                {
                    "Source A": AcquisitionAdapterResult(
                        status="exhausted",
                        reason="no_matching_candidates",
                        diagnostics={"route_used": "fixture"},
                    )
                }
            )
            tool = create_acquire_whitelist_documents_tool(
                registry,
                ArtifactStore(Path(tmp)),
                adapters=[adapter],
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "acquire_whitelist_documents",
                        {
                            "research_direction_id": "dir-detection-warning",
                            "query_bundle": {
                                "queries": [
                                    {
                                        "text": "低空无人机 探测预警",
                                        "language": "zh",
                                        "intent": "evidence_discovery",
                                    },
                                    {
                                        "text": "low altitude drone detection early warning",
                                        "language": "en",
                                        "intent": "evidence_discovery",
                                    },
                                ]
                            },
                            "round_id": "round-1",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(
            [request.queries for request in adapter.received_requests],
            [
                [
                    {
                        "text": "低空无人机 探测预警",
                        "language": "zh",
                        "intent": "evidence_discovery",
                    },
                    {
                        "text": "low altitude drone detection early warning",
                        "language": "en",
                        "intent": "evidence_discovery",
                    },
                ]
            ],
        )
        self.assertEqual(adapter.received_requests[0].entry.source_name, "Source A")
        self.assertEqual(adapter.received_requests[0].round_id, "round-1")
        self.assertEqual(
            adapter.received_requests[0].research_direction_id,
            "dir-detection-warning",
        )
        self.assertEqual(
            result.details["debug"]["diagnostics"]["query_count"],
            2,
        )
        self.assertEqual(
            result.trace_proposals[0].input_refs,
            [
                "低空无人机 探测预警",
                "low altitude drone detection early warning",
            ],
        )

    def test_acquire_whitelist_documents_requires_query_bundle(self) -> None:
        registry = SourceRegistry([_entry("Source A", "a.example.test")])
        tool = create_acquire_whitelist_documents_tool(
            registry,
            ArtifactStore(PROJECT_ROOT / "outputs" / "test-artifacts"),
            adapters=[_RecordingAdapter({})],
        )

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "acquire_whitelist_documents",
                    {"round_id": "round-1"},
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("query_bundle is required", result.content)

    def test_acquire_whitelist_documents_rejects_legacy_query_after_request_object_contract(self) -> None:
        registry = SourceRegistry([_entry("Source A", "a.example.test")])
        tool = create_acquire_whitelist_documents_tool(
            registry,
            ArtifactStore(PROJECT_ROOT / "outputs" / "test-artifacts"),
            adapters=[_RecordingAdapter({})],
        )

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-legacy",
                    "acquire_whitelist_documents",
                    {"query": "低空无人机", "round_id": "round-1"},
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("query_bundle is required", result.content)

    def test_acquire_whitelist_documents_uses_request_object_adapter_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = SourceRegistry([_entry("Source A", "a.example.test")])
            adapter = _RecordingAdapter(
                {
                    "Source A": AcquisitionAdapterResult(
                        status="exhausted",
                        reason="no_matching_candidates",
                        diagnostics={"route_used": "fixture"},
                    )
                }
            )
            tool = create_acquire_whitelist_documents_tool(
                registry,
                ArtifactStore(Path(tmp)),
                adapters=[adapter],
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "acquire_whitelist_documents",
                        {
                            "query_bundle": _query_bundle("低空无人机"),
                            "research_direction_id": "dir-1",
                            "round_id": "round-1",
                            "max_candidates": 7,
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(len(adapter.received_requests), 1)
        request = adapter.received_requests[0]
        self.assertIsInstance(request, SourceAcquisitionRequest)
        self.assertEqual(request.entry.source_name, "Source A")
        self.assertEqual(request.round_id, "round-1")
        self.assertEqual(request.research_direction_id, "dir-1")
        self.assertEqual(request.queries[0]["text"], "低空无人机")
        self.assertEqual(request.max_candidates, 7)

    def test_acquire_whitelist_documents_attempts_all_sources_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = SourceRegistry(
                [
                    _entry("Source A", "a.example.test"),
                    _entry("Source B", "b.example.test"),
                ]
            )
            adapter = _RecordingAdapter(
                {
                    "Source A": AcquisitionAdapterResult(
                        status="ok",
                        documents=[
                            AcquiredDocument(
                                document_id="doc-a",
                                source_name="Source A",
                                source_tier="A",
                                scope="whitelist",
                                route_used="fixture",
                                title="低空无人机探测需求",
                                url="https://a.example.test/doc-a",
                                published_at="2026-01-01",
                                body_artifact_ref="text:a",
                                evidence_preview=[
                                    {
                                        "text": "低空无人机探测预警存在能力短板。",
                                        "location_ref": "text:a#para:0",
                                    }
                                ],
                                evidence_allowed=True,
                                evidence_policy="article_body_allowed",
                                rank_score=9.0,
                                why_ranked="title and preview match the query",
                            )
                        ],
                    ),
                    "Source B": AcquisitionAdapterResult(
                        status="exhausted",
                        reason="no_matching_candidates",
                    ),
                }
            )
            tool = create_acquire_whitelist_documents_tool(
                registry,
                ArtifactStore(Path(tmp)),
                adapters=[adapter],
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "acquire_whitelist_documents",
                        {
                            "query_bundle": _query_bundle("低空无人机探测预警需求"),
                            "round_id": "round-1",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(adapter.attempted_sources, ["Source A", "Source B"])
        self.assertEqual(set(result.details), {"model_payload", "control", "debug"})
        self.assertEqual(result.details["control"]["overall_status"], "partial")
        self.assertEqual(len(result.details["model_payload"]["documents"]), 1)
        document = result.details["model_payload"]["documents"][0]
        self.assertEqual(document["document_id"], "doc-a")
        self.assertNotIn("route_used", document)
        self.assertNotIn("source_tier", document)
        self.assertNotIn("body_artifact_ref", document)
        self.assertNotIn("rank_score", document)
        self.assertEqual(document["source_credibility"], "高可信来源")
        self.assertEqual(document["can_support_evidence"], True)
        self.assertEqual(document["evidence_use"], "正文可作证据")
        self.assertEqual(document["next_action"], "可阅读全文")
        self.assertEqual(
            [
                item["source_name"]
                for item in result.details["control"]["source_statuses"]
            ],
            ["Source A", "Source B"],
        )
        self.assertEqual(
            result.details["control"]["source_statuses"][1]["status"],
            "exhausted",
        )
        self.assertIn("diagnostics_ref", result.details["debug"])
        self.assertIn("acquired 1 documents", result.content)

    def test_acquire_whitelist_documents_surfaces_auth_interrupt(self) -> None:
        registry = SourceRegistry([_entry("Wechat Source", "wechat.example.test")])
        adapter = _RecordingAdapter(
            {
                "Wechat Source": AcquisitionAdapterResult(
                    status="needs_auth",
                    reason="wechat_session_invalid",
                    interrupt={
                        "interrupt_type": "auth_required",
                        "provider": "wechat_mp",
                        "source_name": "Wechat Source",
                        "reason": "wechat_session_invalid",
                        "resume_token": "acq-resume-1",
                        "user_message": "需要重新登录微信公众平台。",
                    },
                )
            }
        )
        tool = create_acquire_whitelist_documents_tool(
            registry,
            ArtifactStore(PROJECT_ROOT / "outputs" / "test-artifacts"),
            adapters=[adapter],
        )

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "acquire_whitelist_documents",
                    {
                        "query_bundle": _query_bundle("低空无人机"),
                        "round_id": "round-1",
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.details["control"]["overall_status"], "needs_auth")
        self.assertEqual(
            result.details["control"]["interrupt"]["provider"],
            "wechat_mp",
        )
        self.assertIn("needs authorization", result.content)

    def test_acquire_whitelist_documents_short_circuits_unreachable_source_health(self) -> None:
        registry = SourceRegistry([_entry("Source A", "a.example.test")])
        adapter = _RecordingAdapter(
            {
                "Source A": AcquisitionAdapterResult(
                    status="ok",
                    documents=[
                        AcquiredDocument(
                            document_id="doc-a",
                            source_name="Source A",
                            source_tier="A",
                            scope="whitelist",
                            route_used="fixture",
                            title="should not be returned",
                            url="https://a.example.test/doc-a",
                            published_at=None,
                            body_artifact_ref="text:a",
                            evidence_preview=[],
                            evidence_allowed=True,
                            evidence_policy="article_body_allowed",
                        )
                    ],
                )
            }
        )
        snapshot = SourceHealthSnapshot(
            snapshot_id="health-1",
            run_id="run-1",
            sources=[
                SourceHealthStatus(
                    source_name="Source A",
                    status="unreachable",
                    reason="entry_url_probe_failed",
                )
            ],
        )
        tool = create_acquire_whitelist_documents_tool(
            registry,
            ArtifactStore(PROJECT_ROOT / "outputs" / "test-artifacts"),
            adapters=[adapter],
            source_health_snapshot=snapshot,
        )

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "acquire_whitelist_documents",
                    {
                        "query_bundle": _query_bundle("低空无人机"),
                        "round_id": "round-1",
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        self.assertEqual(adapter.attempted_sources, [])
        self.assertEqual(result.details["control"]["overall_status"], "exhausted")
        self.assertEqual(
            result.details["control"]["source_statuses"][0],
            {
                "source_name": "Source A",
                "status": "unreachable",
                "reason": "entry_url_probe_failed",
                "action": "skip_source_for_this_round",
            },
        )
        self.assertEqual(result.details["model_payload"]["documents"], [])

    def test_entry_url_probe_adapter_returns_page_preview_without_evidence_claim(self) -> None:
        async def fetch(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            self.assertEqual(url, "https://a.example.test/")
            html = """
            <html>
              <head><title>Source A</title></head>
              <body>
                <main>
                  <h1>低空无人机探测专题</h1>
                  <p>复杂环境下低空无人机探测预警存在能力短板，需要多源融合。</p>
                  <a href="/article/1">低空无人机探测预警能力需求</a>
                </main>
              </body>
            </html>
            """
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=html.encode("utf-8"),
                truncated=False,
            )

        with tempfile.TemporaryDirectory() as tmp:
            registry = SourceRegistry([_entry("Source A", "a.example.test")])
            tool = create_acquire_whitelist_documents_tool(
                registry,
                ArtifactStore(Path(tmp)),
                adapters=[EntryUrlProbeAdapter(fetch)],
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "acquire_whitelist_documents",
                        {
                            "query_bundle": _query_bundle("低空无人机探测预警"),
                            "round_id": "round-1",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(result.details["control"]["overall_status"], "ok")
        document = result.details["model_payload"]["documents"][0]
        self.assertEqual(document["source_credibility"], "高可信来源")
        self.assertFalse(document["can_support_evidence"])
        self.assertEqual(document["evidence_use"], "仅作线索")
        self.assertEqual(document["next_action"], "可阅读全文")
        self.assertNotIn("route_used", document)
        self.assertNotIn("body_artifact_ref", document)
        self.assertIn("低空无人机", document["content_preview"][0]["text"])

    def test_mlpla_journal_adapter_uses_search_api_and_pdf_body_as_evidence(self) -> None:
        requested_get_urls: list[str] = []
        posted_forms: list[dict[str, str]] = []
        pdf_text = (
            "低空无人机探测预警能力存在短板，需要多源融合和快速告警。\n\n"
            "复杂环境下小型无人机目标发现、连续跟踪、识别确认仍面临困难。\n\n"
            "装备研发应关注分布式传感器、智能融合处理和低空快速预警链路。"
        )

        async def search(
            url: str,
            form: dict[str, str],
            timeout_ms: int,
            max_bytes: int,
        ) -> HttpFetchResponse:
            del timeout_ms, max_bytes
            posted_forms.append(dict(form))
            self.assertEqual(
                url,
                "https://journal.mlpla.mil.cn/jsycypg/data/search/advancedSearchResult",
            )
            condition = json.loads(form["searchCondition"])
            self.assertIsInstance(condition, dict)
            self.assertEqual(condition["value"], "低空无人机 探测预警")
            records = []
            if condition["field"] == "abstractinfoCn":
                records = [
                    {
                        "id": "article-1",
                        "titleCn": "低空无人机探测预警能力评估",
                        "abstractinfoCn": "低空无人机探测预警能力存在短板。",
                        "citationCn": "军事运筹与评估, 2026.",
                        "year": "2026",
                        "journal": {
                            "path": "/jsycypg/",
                            "id": "8dca4dc0-494e-4c8c-9925-d13434777e79",
                            "publisherId": "jsycypg",
                        },
                        "articleBusiness": {
                            "pdfFileName": "article-1.pdf",
                            "pdfFileSizeInt": 1024,
                        },
                    }
                ]
            payload = {
                "data": {
                    "pagerFilter": {
                        "totalrecord": len(records),
                        "records": records,
                    }
                }
            }
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/json; charset=utf-8"},
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )

        async def fetch(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            del timeout_ms, max_bytes
            requested_get_urls.append(url)
            self.assertEqual(
                url,
                "https://journal.mlpla.mil.cn/jsycypg/cn/article/pdf/preview/article-1.pdf",
            )
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=pdf_text.encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as tmp:
            registry = SourceRegistry(
                [
                    WhitelistEntry(
                        source_name="军事运筹与评估",
                        source_tier="A",
                        source_type="journal",
                        hosts=["journal.mlpla.mil.cn"],
                        entry_urls=[
                            "https://journal.mlpla.mil.cn/jsycypg/archive_list"
                        ],
                        fetch_transport="http",
                        interaction_profile="static_listing",
                    )
                ]
            )
            tool = create_acquire_whitelist_documents_tool(
                registry,
                ArtifactStore(Path(tmp)),
                adapters=[MlplaJournalAdapter(fetch, search_transport=search)],
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "acquire_whitelist_documents",
                        {
                            "query_bundle": _query_bundle("低空无人机 探测预警"),
                            "round_id": "round-1",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(result.details["control"]["overall_status"], "ok")
        self.assertTrue(posted_forms)
        self.assertEqual(requested_get_urls, [
            "https://journal.mlpla.mil.cn/jsycypg/cn/article/pdf/preview/article-1.pdf"
        ])
        self.assertFalse(any(url.endswith("/archive_list") for url in requested_get_urls))
        document = result.details["model_payload"]["documents"][0]
        self.assertEqual(document["source_name"], "军事运筹与评估")
        self.assertEqual(document["title"], "低空无人机探测预警能力评估")
        self.assertTrue(document["can_support_evidence"])
        self.assertEqual(document["evidence_use"], "正文可作证据")
        self.assertIn("低空无人机", document["content_preview"][0]["text"])
        self.assertNotIn("body_artifact_ref", document)
        self.assertNotIn("article_id", document)
        self.assertNotIn("pdf_url", document)

    def test_mlpla_journal_adapter_does_not_fallback_to_listing_as_evidence(self) -> None:
        async def search(
            url: str,
            form: dict[str, str],
            timeout_ms: int,
            max_bytes: int,
        ) -> HttpFetchResponse:
            del url, form, timeout_ms, max_bytes
            payload = {
                "data": {
                    "pagerFilter": {
                        "totalrecord": 0,
                        "records": [],
                    }
                }
            }
            return HttpFetchResponse(
                url="https://journal.mlpla.mil.cn/jsycypg/data/search/advancedSearchResult",
                status_code=200,
                headers={"content-type": "application/json; charset=utf-8"},
                content=json.dumps(payload).encode("utf-8"),
            )

        async def fetch(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            self.fail(f"empty MLPLA search must not fetch listing or article URL: {url}")

        with tempfile.TemporaryDirectory() as tmp:
            registry = SourceRegistry(
                [
                    WhitelistEntry(
                        source_name="军事运筹与评估",
                        source_tier="A",
                        source_type="journal",
                        hosts=["journal.mlpla.mil.cn"],
                        entry_urls=[
                            "https://journal.mlpla.mil.cn/jsycypg/archive_list"
                        ],
                        fetch_transport="http",
                        interaction_profile="static_listing",
                    )
                ]
            )
            tool = create_acquire_whitelist_documents_tool(
                registry,
                ArtifactStore(Path(tmp)),
                adapters=[MlplaJournalAdapter(fetch, search_transport=search)],
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "acquire_whitelist_documents",
                        {
                            "query_bundle": _query_bundle("不存在的检索词"),
                            "round_id": "round-1",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(result.details["control"]["overall_status"], "exhausted")
        self.assertEqual(result.details["model_payload"]["documents"], [])

    def test_mlpla_journal_adapter_paginates_and_deduplicates_search_records(self) -> None:
        posted_pages: list[int] = []

        async def search(
            url: str,
            form: dict[str, str],
            timeout_ms: int,
            max_bytes: int,
        ) -> HttpFetchResponse:
            del url, timeout_ms, max_bytes
            condition = json.loads(form["searchCondition"])
            page = int(form["currentpage"])
            posted_pages.append(page)
            records = []
            if condition["field"] == "abstractinfoCn":
                if page == 1:
                    records = [
                        _mlpla_record("article-1", "低空无人机探测预警能力评估"),
                        _mlpla_record("article-2", "小型无人机目标发现能力研究"),
                    ]
                elif page == 2:
                    records = [
                        _mlpla_record("article-2", "小型无人机目标发现能力研究"),
                        _mlpla_record("article-3", "复杂环境低空预警体系建设"),
                    ]
            payload = {
                "data": {
                    "pagerFilter": {
                        "totalrecord": 30 if condition["field"] == "abstractinfoCn" else 0,
                        "records": records,
                    }
                }
            }
            return HttpFetchResponse(
                url="https://journal.mlpla.mil.cn/jsycypg/data/search/advancedSearchResult",
                status_code=200,
                headers={"content-type": "application/json; charset=utf-8"},
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )

        async def fetch(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            del timeout_ms, max_bytes
            article_id = url.rsplit("/", 1)[-1].removesuffix(".pdf")
            text = f"{article_id} 低空无人机探测预警正文材料。\n\n" * 8
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=text.encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as tmp:
            adapter = MlplaJournalAdapter(fetch, search_transport=search)
            result = asyncio.run(
                adapter.acquire(
                    request=SourceAcquisitionRequest(
                        entry=WhitelistEntry(
                            source_name="军事运筹与评估",
                            source_tier="A",
                            source_type="journal",
                            hosts=["journal.mlpla.mil.cn"],
                            entry_urls=[
                                "https://journal.mlpla.mil.cn/jsycypg/cn/to_advance_search"
                            ],
                        ),
                        round_id="round-1",
                        research_direction_id="dir-1",
                        queries=[{"text": "低空无人机 探测预警"}],
                        max_candidates=10,
                    ),
                    artifacts=ArtifactStore(Path(tmp)),
                )
            )

        self.assertEqual(result.status, "ok")
        self.assertIn(2, posted_pages)
        self.assertEqual(
            [document.title for document in result.documents],
            [
                "低空无人机探测预警能力评估",
                "小型无人机目标发现能力研究",
                "复杂环境低空预警体系建设",
            ],
        )

    def test_mlpla_journal_adapter_rejects_truncated_pdf_object_dump_as_evidence(self) -> None:
        async def search(
            url: str,
            form: dict[str, str],
            timeout_ms: int,
            max_bytes: int,
        ) -> HttpFetchResponse:
            del url, form, timeout_ms, max_bytes
            payload = {
                "data": {
                    "pagerFilter": {
                        "totalrecord": 1,
                        "records": [
                            _mlpla_record("article-1", "装备供应链安全风险评估指标体系构建")
                        ],
                    }
                }
            }
            return HttpFetchResponse(
                url="https://journal.mlpla.mil.cn/jsycypg/data/search/advancedSearchResult",
                status_code=200,
                headers={"content-type": "application/json; charset=utf-8"},
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )

        async def fetch(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            del url, timeout_ms, max_bytes
            return HttpFetchResponse(
                url="https://journal.mlpla.mil.cn/jsycypg/cn/article/pdf/preview/article-1.pdf",
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=b"1 0 obj<</Type/Catalog>>\nstartxref\n%%EOF",
                truncated=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            registry = SourceRegistry(
                [
                    WhitelistEntry(
                        source_name="军事运筹与评估",
                        source_tier="A",
                        source_type="journal",
                        hosts=["journal.mlpla.mil.cn"],
                        entry_urls=[
                            "https://journal.mlpla.mil.cn/jsycypg/cn/to_advance_search"
                        ],
                    )
                ]
            )
            tool = create_acquire_whitelist_documents_tool(
                registry,
                ArtifactStore(Path(tmp)),
                adapters=[MlplaJournalAdapter(fetch, search_transport=search)],
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "acquire_whitelist_documents",
                        {
                            "query_bundle": _query_bundle("装备"),
                            "round_id": "round-1",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        document = result.details["model_payload"]["documents"][0]
        self.assertFalse(document["can_support_evidence"])
        self.assertEqual(document["evidence_use"], "仅作背景")
        self.assertEqual(document["next_action"], "仅可查看预览")

    def test_mlpla_journal_adapter_overfetches_to_return_readable_evidence_first(self) -> None:
        async def search(
            url: str,
            form: dict[str, str],
            timeout_ms: int,
            max_bytes: int,
        ) -> HttpFetchResponse:
            del url, form, timeout_ms, max_bytes
            payload = {
                "data": {
                    "pagerFilter": {
                        "totalrecord": 2,
                        "records": [
                            _mlpla_record("metadata-only", "装备供应链安全风险评估指标体系构建"),
                            _mlpla_record("readable-body", "基于OODA-DoDAF的反导装备体系结构建模方法研究"),
                        ],
                    }
                }
            }
            return HttpFetchResponse(
                url="https://journal.mlpla.mil.cn/jsycypg/data/search/advancedSearchResult",
                status_code=200,
                headers={"content-type": "application/json; charset=utf-8"},
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )

        async def fetch(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            del timeout_ms, max_bytes
            if "metadata-only" in url:
                return HttpFetchResponse(
                    url=url,
                    status_code=200,
                    headers={"content-type": "application/pdf"},
                    content=b"1 0 obj<</Type/Catalog>>\nstartxref\n%%EOF",
                    truncated=True,
                )
            text = "反导装备体系建模正文材料，涉及装备体系结构、作战活动和能力评估。\n\n" * 6
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=text.encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as tmp:
            registry = SourceRegistry(
                [
                    WhitelistEntry(
                        source_name="军事运筹与评估",
                        source_tier="A",
                        source_type="journal",
                        hosts=["journal.mlpla.mil.cn"],
                        entry_urls=[
                            "https://journal.mlpla.mil.cn/jsycypg/cn/to_advance_search"
                        ],
                    )
                ]
            )
            tool = create_acquire_whitelist_documents_tool(
                registry,
                ArtifactStore(Path(tmp)),
                adapters=[MlplaJournalAdapter(fetch, search_transport=search)],
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "acquire_whitelist_documents",
                        {
                            "query_bundle": _query_bundle("装备"),
                            "round_id": "round-1",
                            "max_candidates": 1,
                            "max_documents": 1,
                        },
                    ),
                    _ctx(),
                )
            )

        document = result.details["model_payload"]["documents"][0]
        self.assertTrue(document["can_support_evidence"])
        self.assertEqual(
            document["title"],
            "基于OODA-DoDAF的反导装备体系结构建模方法研究",
        )

    def test_build_all_tools_exposes_high_level_whitelist_acquisition(self) -> None:
        names = {
            tool.name
            for tool in build_all_tools(
                DomainStore(),
                SourceRegistry([_entry("Source A", "a.example.test")]),
                ArtifactStore(PROJECT_ROOT / "outputs" / "test-artifacts"),
                search_adapters=[],
            )
        }

        self.assertIn("acquire_whitelist_documents", names)
        self.assertIn("read_acquired_document", names)

    def test_read_acquired_document_uses_document_id_not_artifact_ref(self) -> None:
        async def fetch(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            html = """
            <html>
              <body>
                <article>
                  <h1>低空无人机探测预警</h1>
                  <p>低空无人机探测预警能力存在短板。</p>
                  <p>复杂环境下需要多源融合和快速告警。</p>
                </article>
              </body>
            </html>
            """
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=html.encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as tmp:
            tools = build_all_tools(
                DomainStore(),
                SourceRegistry([_entry("Source A", "a.example.test")]),
                ArtifactStore(Path(tmp)),
                search_adapters=[],
                fetch_http_transport=fetch,
            )
            acquire_tool = next(
                tool for tool in tools if tool.name == "acquire_whitelist_documents"
            )
            read_tool = next(
                tool for tool in tools if tool.name == "read_acquired_document"
            )

            acquire_result = asyncio.run(
                acquire_tool.execute(
                    ToolCall(
                        "call-acquire",
                        "acquire_whitelist_documents",
                        {
                            "query_bundle": _query_bundle("低空无人机探测预警"),
                            "round_id": "round-1",
                        },
                    ),
                    _ctx(),
                )
            )
            document_id = acquire_result.details["model_payload"]["documents"][0][
                "document_id"
            ]
            read_result = asyncio.run(
                read_tool.execute(
                    ToolCall(
                        "call-read",
                        "read_acquired_document",
                        {
                            "document_id": document_id,
                            "focus": "探测预警能力短板",
                            "offset": 0,
                            "limit": 2,
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(read_result.is_error)
        self.assertEqual(read_result.details["document_id"], document_id)
        self.assertIn("content", read_result.details)
        self.assertNotIn("artifact_ref", read_result.details)
        self.assertIn("低空无人机", read_result.details["content"][0]["text"])

    def test_read_acquired_document_rejects_metadata_only_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            store = AcquiredDocumentStore()
            store.upsert_many(
                [
                    AcquiredDocument(
                        document_id="doc-metadata",
                        source_name="军事运筹与评估",
                        source_tier="A",
                        scope="whitelist",
                        route_used="mlpla_search_metadata",
                        title="装备供应链安全风险评估指标体系构建",
                        url="https://journal.mlpla.mil.cn/jsycypg/article/id/article-1",
                        published_at="2026",
                        body_artifact_ref="",
                        evidence_preview=[
                            {
                                "text": "为客观全面掌握装备供应链安全状况。",
                                "reason": "metadata only",
                            }
                        ],
                        evidence_allowed=False,
                        evidence_policy="metadata_only",
                    )
                ]
            )
            read_tool = create_read_acquired_document_tool(store, artifacts)

            result = asyncio.run(
                read_tool.execute(
                    ToolCall(
                        "call-read",
                        "read_acquired_document",
                        {"document_id": "doc-metadata"},
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(result.is_error)
        self.assertIn("no readable body", result.content)


class _RecordingAdapter(SourceAcquisitionAdapter):
    def __init__(self, results: dict[str, AcquisitionAdapterResult]) -> None:
        self.results = results
        self.attempted_sources: list[str] = []
        self.received_requests: list[SourceAcquisitionRequest] = []

    def supports(self, entry: WhitelistEntry) -> bool:
        return entry.source_name in self.results

    async def acquire(
        self,
        *,
        request: SourceAcquisitionRequest,
        artifacts: ArtifactStore,
    ) -> AcquisitionAdapterResult:
        del artifacts
        self.attempted_sources.append(request.entry.source_name)
        self.received_requests.append(request)
        return self.results[request.entry.source_name]


def _entry(source_name: str, host: str) -> WhitelistEntry:
    return WhitelistEntry(
        source_name=source_name,
        source_tier="A",
        source_type="official",
        hosts=[host],
        entry_urls=[f"https://{host}/"],
        interaction_profile="static_listing",
    )


def _query_bundle(text: str) -> dict[str, list[dict[str, str]]]:
    return {
        "queries": [
            {
                "text": text,
                "language": "zh",
                "intent": "evidence_discovery",
            }
        ]
    }


def _mlpla_record(article_id: str, title: str) -> dict[str, object]:
    return {
        "id": article_id,
        "titleCn": title,
        "abstractinfoCn": "低空无人机探测预警能力存在短板。",
        "citationCn": "军事运筹与评估, 2026.",
        "year": "2026",
        "journal": {
            "path": "/jsycypg/",
            "id": "8dca4dc0-494e-4c8c-9925-d13434777e79",
            "publisherId": "jsycypg",
        },
        "articleBusiness": {
            "pdfFileName": f"{article_id}.pdf",
            "pdfFileSizeInt": 1024,
        },
    }


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="run-1",
        agent_run_id="agent-1",
        worker_id="worker-1",
    )
