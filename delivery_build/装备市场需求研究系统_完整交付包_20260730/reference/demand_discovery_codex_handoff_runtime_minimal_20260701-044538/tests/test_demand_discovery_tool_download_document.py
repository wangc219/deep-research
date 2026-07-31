from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "demand_discovery_pages"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry, WhitelistEntry  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.documents import create_read_document_tool  # noqa: E402
from knowledgegraph.demand_discovery.tools.discovery import create_download_document_tool  # noqa: E402
from knowledgegraph.demand_discovery.tools.network import HttpFetchResponse  # noqa: E402


class DemandDiscoveryDownloadDocumentToolTests(unittest.TestCase):
    def test_downloads_html_txt_and_pdf_into_readable_text_artifacts(self) -> None:
        async def transport(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            if url.endswith(".txt"):
                return HttpFetchResponse(url, 200, {"content-type": "text/plain; charset=utf-8"}, "txt paragraph".encode())
            if url.endswith(".pdf"):
                return HttpFetchResponse(url, 200, {"content-type": "application/pdf"}, b"%PDF-1.4\nPDF extracted paragraph\n%%EOF")
            return HttpFetchResponse(
                url,
                200,
                {"content-type": "text/html; charset=utf-8"},
                (FIXTURE_ROOT / "article_with_pdf.html").read_bytes(),
            )

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            tool = create_download_document_tool(
                DomainStore(),
                SourceRegistry([_entry()]),
                artifacts,
                http_transport=transport,
            )
            html_result = _run(tool, {"url": "https://example.test/article.html"})
            txt_result = _run(tool, {"url": "https://example.test/readme.txt"})
            pdf_result = _run(tool, {"url": "https://example.test/report.pdf"})
            read_tool = create_read_document_tool(artifacts)
            read_result = _run(read_tool, {"artifact_ref": pdf_result.details["text_artifact_ref"]})

        self.assertFalse(html_result.is_error)
        self.assertFalse(txt_result.is_error)
        self.assertFalse(pdf_result.is_error)
        self.assertTrue(html_result.details["text_artifact_ref"].startswith("text:"))
        self.assertTrue(txt_result.details["text_artifact_ref"].startswith("text:"))
        self.assertTrue(pdf_result.details["raw_artifact_ref"].startswith("pdf:"))
        self.assertIn("PDF extracted paragraph", read_result.content)
        self.assertNotIn("EvidenceCard", {proposal.object_type for proposal in pdf_result.domain_proposals})

    def test_docx_only_stores_raw_artifact_and_metadata(self) -> None:
        async def transport(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            return HttpFetchResponse(
                url,
                200,
                {"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
                b"PK fake docx",
            )

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            tool = create_download_document_tool(
                DomainStore(),
                SourceRegistry([_entry()]),
                artifacts,
                http_transport=transport,
            )
            result = _run(tool, {"url": "https://example.test/report.docx"})

            self.assertFalse(result.is_error)
            self.assertTrue(artifacts.exists(result.details["raw_artifact_ref"]))
            self.assertNotIn("text_artifact_ref", result.details)
            self.assertEqual(result.details["status"], "skipped_pending_parser")
            self.assertEqual(result.domain_proposals, [])


def _run(tool, args):
    return asyncio.run(tool.execute(ToolCall("call-1", tool.name, args), _ctx()))


def _entry() -> WhitelistEntry:
    return WhitelistEntry(
        source_name="Fixture Source",
        source_tier="A",
        source_type="official",
        hosts=["example.test"],
        fetch_transport="http",
        rate_limit_ms=0,
    )


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "reader", {})


if __name__ == "__main__":
    unittest.main()
