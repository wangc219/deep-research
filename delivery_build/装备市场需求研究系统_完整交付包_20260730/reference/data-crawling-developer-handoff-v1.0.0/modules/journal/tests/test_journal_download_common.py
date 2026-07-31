from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import inspect
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "journal"))

import journal_download_common as common  # noqa: E402


class JournalDownloadCommonTests(unittest.TestCase):
    def test_load_completed_paper_ids_uses_only_successful_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "manifest.jsonl"
            records = [
                {"status": "downloaded", "paper": {"article_id": "paper-a"}},
                {"status": "failed", "paper": {"article_id": "paper-b"}},
                {"status": "skipped_existing", "paper": {"article_id": "paper-c"}},
            ]
            manifest.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
                encoding="utf-8",
            )

            completed = common.load_completed_paper_ids(manifest)

        self.assertEqual(completed, {"paper-a", "paper-c"})

    def test_should_skip_existing_nonempty_file_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "existing.pdf"
            path.write_bytes(b"%PDF-1.4")

            decision = common.skip_reason(
                paper_id="paper-a",
                output_path=path,
                completed_ids=set(),
                force=False,
            )

        self.assertEqual(decision, "file_exists")

    def test_force_disables_manifest_and_file_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "existing.pdf"
            path.write_bytes(b"%PDF-1.4")

            decision = common.skip_reason(
                paper_id="paper-a",
                output_path=path,
                completed_ids={"paper-a"},
                force=True,
            )

        self.assertIsNone(decision)

    def test_safe_header_value_escapes_non_ascii_response_headers(self) -> None:
        self.assertEqual(common.safe_header_value("attachment; filename=abcÉ.pdf"), "attachment; filename=abc\\xc9.pdf")

    def test_request_bytes_preserves_cookies_across_redirects(self) -> None:
        class RedirectCookieHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Set-Cookie", "session=ok; Path=/")
                    self.send_header("Location", "/final")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                body = b"ok" if "session=ok" in self.headers.get("Cookie", "") else b"missing"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectCookieHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)

        data, _headers = common.request_bytes(f"http://127.0.0.1:{server.server_port}/start")

        self.assertEqual(data, b"ok")

    def test_request_bytes_retries_remote_disconnect_once(self) -> None:
        class FlakyHandler(BaseHTTPRequestHandler):
            attempts = 0

            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                type(self).attempts += 1
                if type(self).attempts == 1:
                    self.connection.close()
                    return

                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), FlakyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)

        data, _headers = common.request_bytes(f"http://127.0.0.1:{server.server_port}/flaky")

        self.assertEqual(data, b"ok")
        self.assertEqual(FlakyHandler.attempts, 2)

    def test_request_bytes_accepts_attempt_override(self) -> None:
        parameters = inspect.signature(common.request_bytes).parameters

        self.assertIn("attempts", parameters)

    def test_request_text_uses_declared_gb18030_charset(self) -> None:
        body = "中文标题".encode("gb18030")
        with patch.object(
            common,
            "request_bytes",
            return_value=(body, {"Content-Type": "text/html; charset=gb18030"}),
        ):
            text = common.request_text("https://example.test")

        self.assertEqual(text, "中文标题")


if __name__ == "__main__":
    unittest.main()
