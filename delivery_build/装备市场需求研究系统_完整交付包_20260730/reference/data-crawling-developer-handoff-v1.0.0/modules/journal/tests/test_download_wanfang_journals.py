from __future__ import annotations

from contextlib import redirect_stdout
from http.client import IncompleteRead, RemoteDisconnected
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "journal"))

import download_xxdkjs  # noqa: E402
import wanfang_journal_downloader as wanfang  # noqa: E402


class WanfangJournalDownloadTests(unittest.TestCase):
    def test_parse_transaction_location_extracts_product_title(self) -> None:
        location = (
            "https://my.wanfangdata.com.cn/user/transaction?"
            "webTransactionRequest=eyJ0cmFuc2FjdGlvblJlcXVlc3QiOnsicHJvZHVjdFRpdGxlIjoi"
            "5rWL6K-V6K665paHIn19"
        )

        title = wanfang.parse_transaction_title(location)

        self.assertEqual(title, "测试论文")

    def test_discover_papers_enumerates_issue_ids_until_consecutive_misses(self) -> None:
        config = wanfang.WanfangJournalConfig(
            journal_id="xxdkjs",
            journal_name="信息对抗技术",
            output_slug="xxdkjs",
        )
        found = {
            "xxdkjs202601001": wanfang.Paper(
                article_id="xxdkjs202601001",
                title="第一篇",
                detail_url="https://d.wanfangdata.com.cn/periodical/xxdkjs202601001",
                download_url="https://oss.wanfangdata.com.cn/file/download/perio_xxdkjs202601001.aspx",
                source_page="source",
            ),
            "xxdkjs202601002": wanfang.Paper(
                article_id="xxdkjs202601002",
                title="第二篇",
                detail_url="https://d.wanfangdata.com.cn/periodical/xxdkjs202601002",
                download_url="https://oss.wanfangdata.com.cn/file/download/perio_xxdkjs202601002.aspx",
                source_page="source",
            ),
        }

        def fake_probe(article_id: str, source_page: str) -> wanfang.Paper | None:
            paper = found.get(article_id)
            if paper:
                paper.source_page = source_page
            return paper

        papers = wanfang.discover_issue_papers(
            config=config,
            year="2026",
            issue="1",
            max_seq=5,
            stop_after_misses=2,
            probe=fake_probe,
        )

        self.assertEqual([paper.article_id for paper in papers], ["xxdkjs202601001", "xxdkjs202601002"])
        self.assertEqual(papers[0].source_page, wanfang.build_issue_url(config, "2026", "1"))

    def test_probe_download_retries_transient_head_timeout(self) -> None:
        with patch.object(
            wanfang,
            "request_head_no_redirect",
            side_effect=[URLError("timed out"), (404, {})],
        ) as request_head:
            paper = wanfang.probe_wanfang_download("xxdkjs202601999", "source")

        self.assertIsNone(paper)
        self.assertEqual(request_head.call_count, 2)

    def test_wrapper_main_uses_configured_journal_for_year_issue_dry_run(self) -> None:
        paper = wanfang.Paper(
            article_id="xxdkjs202601001",
            title="第一篇",
            detail_url="https://d.wanfangdata.com.cn/periodical/xxdkjs202601001",
            download_url="https://oss.wanfangdata.com.cn/file/download/perio_xxdkjs202601001.aspx",
            source_page="source",
        )
        with (
            patch.object(wanfang, "discover_issue_papers", return_value=[paper]) as discover,
            redirect_stdout(StringIO()) as stdout,
        ):
            exit_code = download_xxdkjs.main(
                ["--year", "2026", "--issue", "1", "--max-papers", "-1", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        discover.assert_called_once()
        self.assertEqual(json.loads(stdout.getvalue())[0]["article_id"], "xxdkjs202601001")

    def test_download_pdf_follows_newfulltext_link_from_download_info_page(self) -> None:
        paper = wanfang.Paper(
            article_id="xxdkjs202601001",
            title="第一篇",
            detail_url="https://d.wanfangdata.com.cn/periodical/xxdkjs202601001",
            download_url="https://oss.wanfangdata.com.cn/file/download/perio_xxdkjs202601001.aspx",
            source_page="source",
        )
        download_info_html = (
            '<html><body><iframe src="/NewFulltext?type=perio&amp;'
            'resourceId=xxdkjs202601001&amp;transaction=%7B%7D"></iframe></body></html>'
        ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                wanfang,
                "request_bytes",
                side_effect=[
                    (download_info_html, {"Content-Type": "text/html; charset=utf-8"}),
                    (b"%PDF-1.4\ncontent", {"Content-Type": "application/pdf"}),
                ],
            ) as request_bytes:
                record = wanfang.download_pdf(paper, Path(tmpdir))

            self.assertEqual(record["status"], "downloaded")
            self.assertEqual(record["download_url"], paper.download_url)
            self.assertEqual(record["download_flow"], "new_fulltext")
            self.assertTrue(Path(str(record["file"])).read_bytes().startswith(b"%PDF-1.4"))
            self.assertEqual(request_bytes.call_count, 2)

    def test_download_pdf_retries_transient_incomplete_pdf_stream(self) -> None:
        paper = wanfang.Paper(
            article_id="xxdkjs202601001",
            title="第一篇",
            detail_url="https://d.wanfangdata.com.cn/periodical/xxdkjs202601001",
            download_url="https://oss.wanfangdata.com.cn/file/download/perio_xxdkjs202601001.aspx",
            source_page="source",
        )
        download_info_html = (
            '<html><body><iframe src="/NewFulltext?type=perio&amp;'
            'resourceId=xxdkjs202601001&amp;transaction=%7B%7D"></iframe></body></html>'
        ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                wanfang,
                "request_bytes",
                side_effect=[
                    (download_info_html, {"Content-Type": "text/html; charset=utf-8"}),
                    IncompleteRead(b"%PDF-1.4\npartial"),
                    (b"%PDF-1.4\ncontent", {"Content-Type": "application/pdf"}),
                ],
            ) as request_bytes:
                record = wanfang.download_pdf(paper, Path(tmpdir))

            self.assertEqual(record["status"], "downloaded")
            self.assertEqual(record["download_flow"], "new_fulltext")
            self.assertTrue(Path(str(record["file"])).read_bytes().startswith(b"%PDF-1.4"))
            self.assertEqual(request_bytes.call_count, 3)

    def test_download_pdf_retries_remote_disconnect_before_response(self) -> None:
        paper = wanfang.Paper(
            article_id="dzdkjs200505009",
            title="瞬断论文",
            detail_url="https://d.wanfangdata.com.cn/periodical/dzdkjs200505009",
            download_url="https://oss.wanfangdata.com.cn/file/download/perio_dzdkjs200505009.aspx",
            source_page="source",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                wanfang,
                "request_bytes",
                side_effect=[
                    RemoteDisconnected("Remote end closed connection without response"),
                    (b"%PDF-1.4\ncontent", {"Content-Type": "application/pdf"}),
                ],
            ) as request_bytes:
                record = wanfang.download_pdf(paper, Path(tmpdir))

            self.assertEqual(record["status"], "downloaded")
            self.assertEqual(record["download_flow"], "direct")
            self.assertTrue(Path(str(record["file"])).read_bytes().startswith(b"%PDF-1.4"))
            self.assertEqual(request_bytes.call_count, 2)


if __name__ == "__main__":
    unittest.main()
