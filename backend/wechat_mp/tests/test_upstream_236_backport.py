import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend import accounts as accounts_module
from backend import articles as articles_module
from backend import auth as auth_module
from backend import waterwall


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        return self._payload


class TestUpstream236Backport(unittest.TestCase):
    def tearDown(self):
        waterwall.waterwall_reset()
        auth_module._poll_stop_event.clear()

    def test_qr_poll_sends_last_404_after_scan(self):
        class Session:
            def __init__(self):
                self.urls = []

            def get(self, url, **_kwargs):
                self.urls.append(url)
                if len(self.urls) == 1:
                    return FakeResponse({"wx_errcode": 404})
                return FakeResponse({"wx_errcode": 402})

        session = Session()
        with patch("backend.auth.get_weread_session", return_value=session):
            auth_module._background_poll_login("qr-uuid", {})

        self.assertNotIn("last=404", session.urls[0])
        self.assertIn("last=404", session.urls[1])

    def test_account_search_stops_fallback_after_2014(self):
        class Session:
            def __init__(self):
                self.urls = []

            def get(self, url, **_kwargs):
                self.urls.append(url)
                return FakeResponse({"errcode": -2014}, 499, '{"errcode":-2014}')

        app = Flask(__name__)
        app.register_blueprint(accounts_module.accounts_bp)
        session = Session()
        with (
            patch(
                "backend.accounts.borrow_weread_session",
                return_value=("account", "vid", "token", {}),
            ),
            patch("backend.accounts.get_weread_session", return_value=session),
            patch("backend.accounts.account_pool.report"),
            patch("backend.accounts.time.sleep"),
        ):
            response = app.test_client().post(
                "/api/accounts/search",
                json={"keyword": "防务观察"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(session.urls), 2)
        self.assertTrue(waterwall.is_waterwall_active())

    def test_article_mobile_fallback_stops_requests_after_2014(self):
        class Session:
            def __init__(self):
                self.urls = []

            def get(self, url, **_kwargs):
                self.urls.append(url)
                return FakeResponse({"errcode": -2014}, 499, '{"errcode":-2014}')

        session = Session()
        with (
            patch("backend.articles._fetch_web_articles_page", side_effect=RuntimeError("degraded")),
            patch("backend.articles.biz_to_book_id", return_value="MP_WXS_1"),
            patch("backend.articles.get_weread_session", return_value=session),
            patch(
                "backend.articles.borrow_weread_session",
                return_value=("account", "vid", "token", {}),
            ),
            patch("backend.articles.account_pool.report"),
            patch("backend.articles.time.sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "分页暂时不可用"):
                articles_module._fetch_articles_page("account", 0, 20)

        self.assertEqual(len(session.urls), 4)
        self.assertTrue(waterwall.is_waterwall_active())

    def test_web_history_rotates_account_before_global_circuit_breaker(self):
        class Session:
            def __init__(self):
                self.calls = 0

            def get(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponse(
                        {"errCode": -2014, "errMsg": "请求频率过高"},
                        200,
                        '{"errCode":-2014}',
                    )
                return FakeResponse({"reviews": [{"subReviews": []}]})

        session = Session()
        with (
            patch("backend.articles.get_weread_session", return_value=session),
            patch(
                "backend.articles.borrow_weread_session",
                side_effect=[
                    ("account-1", "vid-1", "token-1", {}),
                    ("account-2", "vid-2", "token-2", {}),
                ],
            ),
            patch("backend.articles.account_pool.report") as report,
            patch("backend.articles.sleep_backoff"),
        ):
            result = articles_module._fetch_web_history_batch("MP_WXS_1", 0)

        self.assertEqual(len(result["reviews"]), 1)
        self.assertEqual(session.calls, 2)
        self.assertEqual(report.call_count, 2)
        self.assertFalse(waterwall.is_waterwall_active())

    def test_serve_file_allows_markdown_and_rejects_config_files(self):
        app = Flask(__name__)
        app.register_blueprint(articles_module.articles_bp)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown = root / "article.md"
            config = root / "accounts.json"
            markdown.write_text("# 正文", encoding="utf-8")
            config.write_text('{"token":"secret"}', encoding="utf-8")

            with patch("backend.articles.get_settings", return_value={"download_dir": directory}):
                client = app.test_client()
                markdown_response = client.get(
                    "/api/articles/serve-file",
                    query_string={"path": str(markdown)},
                )
                config_response = client.get(
                    "/api/articles/serve-file",
                    query_string={"path": str(config)},
                )

        self.assertEqual(markdown_response.status_code, 200)
        self.assertIn("<h1>正文</h1>", markdown_response.get_data(as_text=True))
        self.assertEqual(config_response.status_code, 403)

    def test_frontend_contains_scan_debounce_and_quick_dates(self):
        login = (PROJECT_ROOT / "frontend/js/components/login.js").read_text(encoding="utf-8")
        articles = (PROJECT_ROOT / "frontend/js/components/articles.js").read_text(encoding="utf-8")
        api = (PROJECT_ROOT / "frontend/js/api.js").read_text(encoding="utf-8")

        self.assertIn("this._loginStartTime = Date.now()", login)
        self.assertIn("< 3500", login)
        self.assertIn('id="article-quick-date"', articles)
        self.assertIn("onQuickDateChange(type)", articles)
        self.assertIn("按时间搜索", articles)
        self.assertIn("async searchDateRange()", articles)
        self.assertIn("hasActiveSearch()", articles)
        self.assertIn("start_time: startTime", api)
        self.assertIn("end_time: endTime", api)
        self.assertIn("data.waterwall && data.waterwall.active", api)

    def test_frontend_batch_select_skips_processed_articles(self):
        articles = (PROJECT_ROOT / "frontend/js/components/articles.js").read_text(encoding="utf-8")

        self.assertIn("全选未下载", articles)
        self.assertIn("isBatchSelectable(article)", articles)
        self.assertIn("['downloaded', 'importing', 'imported']", articles)
        self.assertIn("article.download_scope === 'global'", articles)
        self.assertIn("this.selectedArticles.delete(globalIdx)", articles)


if __name__ == "__main__":
    unittest.main()
