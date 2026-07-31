from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.open_search import (  # noqa: E402
    OpenSearchPlan,
    OpenSourceLead,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.network import HttpFetchResponse  # noqa: E402
from knowledgegraph.demand_discovery.tools.open_fetch import create_fetch_open_source_page_tool  # noqa: E402


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class DemandDiscoveryOpenSourceFetchTests(unittest.TestCase):
    def test_fetch_open_source_stores_body_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            tool = create_fetch_open_source_page_tool(
                _store(),
                artifacts,
                http_transport=_html_transport,
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "fetch_open_source_page",
                        {
                            "open_search_plan_id": "osp-1",
                            "open_source_lead_id": "osl-1",
                            "url": "https://open.example.test/report",
                        },
                    ),
                    _ctx(),
                )
            )

            text = artifacts.get_text(result.details["simplified_ref"])

        self.assertFalse(result.is_error)
        self.assertEqual(result.domain_proposals[0].object_type, "OpenSourceBodyArtifact")
        self.assertEqual(result.details["open_source_lead_id"], "osl-1")
        self.assertIn("公开正文第一段", text)

    def test_fetch_open_source_rejects_url_mismatch_and_bad_scheme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = create_fetch_open_source_page_tool(
                _store(url="javascript:alert(1)", domain=""),
                ArtifactStore(Path(tmp)),
                http_transport=_html_transport,
            )
            bad_scheme = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "fetch_open_source_page",
                        {
                            "open_search_plan_id": "osp-1",
                            "open_source_lead_id": "osl-1",
                            "url": "javascript:alert(1)",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(bad_scheme.is_error)
        self.assertIn("unsupported URL scheme", bad_scheme.content)

        with tempfile.TemporaryDirectory() as tmp:
            tool = create_fetch_open_source_page_tool(
                _store(),
                ArtifactStore(Path(tmp)),
                http_transport=_html_transport,
            )
            mismatch = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-2",
                        "fetch_open_source_page",
                        {
                            "open_search_plan_id": "osp-1",
                            "open_source_lead_id": "osl-1",
                            "url": "https://other.example.test/report",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(mismatch.is_error)
        self.assertIn("url does not match OpenSourceLead", mismatch.content)

    def test_fetch_open_source_rejects_pdf_content_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = create_fetch_open_source_page_tool(
                _store(),
                ArtifactStore(Path(tmp)),
                http_transport=_pdf_transport,
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "fetch_open_source_page",
                        {
                            "open_search_plan_id": "osp-1",
                            "open_source_lead_id": "osl-1",
                            "url": "https://open.example.test/report",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(result.is_error)
        self.assertIn("supports html/txt only", result.content)


async def _html_transport(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
    return HttpFetchResponse(
        url=url,
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=(
            "<html><title>Open Report</title><body>"
            "<p>公开正文第一段。</p><p>公开正文第二段。</p>"
            "</body></html>"
        ).encode("utf-8"),
    )


async def _pdf_transport(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
    return HttpFetchResponse(
        url=url,
        status_code=200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-1.7",
    )


def _store(
    *,
    url: str = "https://open.example.test/report",
    domain: str = "open.example.test",
) -> DomainStore:
    store = DomainStore()
    store.upsert_open_search_plan(
        OpenSearchPlan(
            plan_id="osp-1",
            run_id="run-1",
            round_id="round-1",
            topic="远海保障",
            trigger_judgement_id="judge-1",
            trigger_reason="白名单耗尽后补证",
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
            topic="远海保障",
            url=url,
            domain=domain,
            title="Open report",
            snippet="公开报告",
            source_name_guess="Open Example",
            search_query="远海保障 缺口",
            source_scope="open_web",
            quality_status="pending",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return store


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "reader", {})


if __name__ == "__main__":
    unittest.main()
