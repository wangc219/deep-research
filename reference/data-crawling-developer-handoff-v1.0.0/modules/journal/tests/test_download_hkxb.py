from __future__ import annotations

from contextlib import redirect_stdout
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

import download_hkxb  # noqa: E402


YEAR_HTML = """
<a href="/CN/volumn/volumn_1559.shtml">· 2023&nbsp;Vol.44&nbsp;No.2&nbsp; pp.0-627181</a>
<a href="/CN/volumn/volumn_1558.shtml">· 2023&nbsp;Vol.44&nbsp;No.1&nbsp; pp.0-627971</a>
"""

RELATIVE_YEAR_HTML = """
<a href="../volumn/volumn_1558.shtml" class="fl" target="_blank">
· 2023&nbsp;Vol.44&nbsp;No.1&nbsp;
pp.0-627971&nbsp;&nbsp;2023-01-16</a>
"""

ISSUE_HTML = """
<a href="/CN/article/showTenYearOldVolumn.do">过刊一览</a>
<a href="/CN/abstract/abstract19433.shtml">2023年第44卷第1期电子期刊</a>
<a href="#1" onclick="lsdy1('PDF','19433','https://hkxb.buaa.edu.cn','2023','1558');return false;">PDF</a>
<a href="/CN/10.7527/S1000-6893.2022.26973">飞机过冷大水滴结冰气象条件运行设计挑战</a>
<a href="/CN/10.7527/S1000-6893.2022.26973">摘要</a>
<span>陈勇, 孔维梁, 刘洪</span>
<a href="#1" onclick="lsdy1('PDF','19087','https://hkxb.buaa.edu.cn','2023','1558');return false;">PDF</a>
<a href="#1" onclick="lsdy1('PDF','19087','https://hkxb.buaa.edu.cn','2023','1558');return false;">下载</a>
<a href="/CN/10.7527/S1000-6893.2022.27211">翼型结冰状态复杂分离流动数值模拟综述</a>
<a href="#1" onclick="lsdy1('PDF','19170','https://hkxb.buaa.edu.cn','2023','1558');return false;">PDF</a>
"""


class DownloadHkxbTests(unittest.TestCase):
    def test_select_issue_url_matches_year_and_issue(self) -> None:
        url = download_hkxb.select_issue_url(YEAR_HTML, year="2023", issue="1")

        self.assertEqual(url, "https://hkxb.buaa.edu.cn/CN/volumn/volumn_1558.shtml")

    def test_select_issue_url_handles_relative_archive_links(self) -> None:
        url = download_hkxb.select_issue_url(RELATIVE_YEAR_HTML, year="2023", issue="1")

        self.assertEqual(url, "https://hkxb.buaa.edu.cn/CN/volumn/volumn_1558.shtml")

    def test_parse_papers_skips_full_issue_and_deduplicates_pdf_links(self) -> None:
        papers = download_hkxb.parse_papers(
            ISSUE_HTML,
            source_page="https://hkxb.buaa.edu.cn/CN/volumn/volumn_1558.shtml",
        )

        self.assertEqual([paper.article_id for paper in papers], ["19087", "19170"])
        self.assertEqual(
            [paper.title for paper in papers],
            ["飞机过冷大水滴结冰气象条件运行设计挑战", "翼型结冰状态复杂分离流动数值模拟综述"],
        )

    def test_parse_pdf_payload_extracts_pdf_url(self) -> None:
        payload = (
            '[json]{"pdfUrl":"https://hkxb.buaa.edu.cn/CN/PDF/10.7527/'
            'S1000-6893.2022.26973?token=abc","status":1}'
        )

        self.assertEqual(
            download_hkxb.parse_pdf_payload(payload),
            "https://hkxb.buaa.edu.cn/CN/PDF/10.7527/S1000-6893.2022.26973?token=abc",
        )

    def test_parse_pdf_payload_removes_spaces_from_malformed_pdf_url(self) -> None:
        payload = (
            '[json]{"pdfUrl":"https://hkxb.buaa.edu.cn/CN/PDF/10. 7527/'
            'S1000-6893. 2022. 27496?token=abc","status":1}'
        )

        self.assertEqual(
            download_hkxb.parse_pdf_payload(payload),
            "https://hkxb.buaa.edu.cn/CN/PDF/10.7527/S1000-6893.2022.27496?token=abc",
        )

    def test_json_line_escapes_symbols_not_supported_by_windows_gbk_console(self) -> None:
        line = download_hkxb.json_line({"title": "主动学习基自适应PC⁃Kriging模型"})

        self.assertIn("\\u2043", line)
        self.assertEqual(json.loads(line)["title"], "主动学习基自适应PC⁃Kriging模型")

    def test_main_uses_year_and_issue_to_discover_papers(self) -> None:
        def fake_request_text(url: str, headers: dict[str, str] | None = None) -> str:
            if url == "https://hkxb.buaa.edu.cn/CN/article/showTenYearVolumnDetail.do?nian=2023":
                return YEAR_HTML
            if url == "https://hkxb.buaa.edu.cn/CN/volumn/volumn_1558.shtml":
                return ISSUE_HTML
            raise AssertionError(f"unexpected URL: {url}")

        with (
            patch.object(download_hkxb, "request_text", side_effect=fake_request_text),
            redirect_stdout(StringIO()) as stdout,
        ):
            exit_code = download_hkxb.main(
                ["--year", "2023", "--issue", "1", "--max-papers", "-1", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())[0]["article_id"], "19087")

    def test_download_pdf_retries_transient_urlopen_error(self) -> None:
        paper = download_hkxb.Paper(
            article_id="19433",
            title="飞机过冷大水滴结冰气象条件运行设计挑战",
            article_page="https://hkxb.buaa.edu.cn/CN/10.7527/S1000-6893.2022.26973",
            source_page="https://hkxb.buaa.edu.cn/CN/volumn/volumn_1558.shtml",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.object(
                    download_hkxb,
                    "resolve_pdf_url",
                    return_value="https://hkxb.buaa.edu.cn/CN/PDF/10.7527/S1000-6893.2022.26973?token=abc",
                ),
                patch.object(
                    download_hkxb,
                    "request_bytes",
                    side_effect=[
                        URLError("timed out"),
                        (b"%PDF-1.4\ncontent", {"Content-Type": "application/pdf"}),
                    ],
                ) as request_bytes,
            ):
                record = download_hkxb.download_pdf(paper, Path(tmpdir))

            self.assertEqual(record["status"], "downloaded")
            self.assertTrue(Path(str(record["file"])).read_bytes().startswith(b"%PDF-1.4"))
            self.assertEqual(request_bytes.call_count, 2)


if __name__ == "__main__":
    unittest.main()
