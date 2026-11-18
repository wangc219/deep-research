import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend import articles as articles_module


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""
        self.headers = {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, chapter_payload):
        self.chapter_payload = chapter_payload
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        if "/mp/chapters" in url:
            return FakeResponse(self.chapter_payload)
        if "/article/list" in url:
            return FakeResponse({"reviews": [{"reviewId": "unexpected", "title": "错误兜底"}]})
        return FakeResponse({}, status_code=404)


class FakeWebSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == articles_module._WEB_HISTORY_URL:
            payload = self.payload(kwargs["params"]["offset"]) if callable(self.payload) else self.payload
            return FakeResponse(payload)
        return FakeResponse({}, status_code=404)


class TestArticlePaginationAndState(unittest.TestCase):
    def setUp(self):
        articles_module._web_history_cache.clear()
        articles_module._web_page_count_cache.clear()
        app = Flask(__name__)
        app.register_blueprint(articles_module.articles_bp)
        self.client = app.test_client()

    @patch("backend.articles._apply_article_download_states")
    @patch("backend.articles._fetch_articles_page")
    def test_exact_total_pages(self, fetch, apply_states):
        fetch.return_value = (
            [{"title": "文章", "link": "https://mp.weixin.qq.com/s/a"}],
            21,
            1,
            True,
            True,
        )

        response = self.client.get("/api/articles/list/account?begin=10&count=10")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["total_exact"])
        self.assertTrue(payload["total_pages_exact"])
        self.assertEqual(payload["total_pages"], 3)
        self.assertEqual(payload["minimum_total_pages"], 3)
        apply_states.assert_called_once()

    @patch("backend.articles._apply_article_download_states")
    @patch("backend.articles._fetch_articles_page")
    def test_unknown_total_returns_minimum_pages_without_probing(self, fetch, _apply_states):
        fetch.return_value = ([{"title": "文章"}], 21, 1, False, False)

        response = self.client.get("/api/articles/list/account?begin=10&count=10")

        payload = response.get_json()
        self.assertFalse(payload["total_exact"])
        self.assertFalse(payload["total_pages_exact"])
        self.assertIsNone(payload["total_pages"])
        self.assertEqual(payload["minimum_total_pages"], 3)
        fetch.assert_called_once()

    @patch("backend.articles._apply_article_download_states")
    @patch("backend.articles._fetch_articles_page")
    def test_empty_page_confirms_previous_page_as_last(self, fetch, _apply_states):
        fetch.return_value = ([], 80, 0, False, True)

        response = self.client.get("/api/articles/list/account?begin=80&count=20")

        payload = response.get_json()
        self.assertTrue(payload["terminal_empty"])
        self.assertTrue(payload["total_pages_exact"])
        self.assertEqual(payload["total_pages"], 4)
        self.assertEqual(payload["minimum_total_pages"], 4)

    @patch("backend.articles._apply_article_download_states")
    @patch("backend.articles._fetch_articles_page")
    def test_explicit_last_nonempty_page_returns_exact_page_count(self, fetch, _apply_states):
        fetch.return_value = ([{"title": f"文章 {index}"} for index in range(19)], 79, 0, False, True)

        response = self.client.get("/api/articles/list/account?begin=60&count=20")

        payload = response.get_json()
        self.assertFalse(payload["terminal_empty"])
        self.assertTrue(payload["total_pages_exact"])
        self.assertEqual(payload["total_pages"], 4)
        self.assertEqual(payload["minimum_total_pages"], 4)

    def test_short_nonempty_page_keeps_conservative_continuation(self):
        has_more, exact, total = articles_module._parse_upstream_pagination(
            {},
            offset=60,
            returned_count=19,
        )

        self.assertTrue(has_more)
        self.assertFalse(exact)
        self.assertIsNone(total)

    def test_empty_page_is_an_exact_terminal_signal(self):
        has_more, exact, total = articles_module._parse_upstream_pagination(
            {},
            offset=80,
            returned_count=0,
        )

        self.assertFalse(has_more)
        self.assertTrue(exact)
        self.assertIsNone(total)

    def test_sparse_page_count_discovers_and_caches_exact_total(self):
        calls = []

        def fetch_batch(_book_id, offset):
            calls.append(offset)
            page_index = offset // 20
            return {"reviews": [{"page": page_index}]} if page_index < 37 else {"reviews": []}

        with patch("backend.articles._fetch_web_history_batch", side_effect=fetch_batch):
            first = articles_module._discover_web_total_pages("book", 20)
            second = articles_module._discover_web_total_pages("book", 20)

        self.assertEqual(first, 37)
        self.assertEqual(second, 37)
        self.assertLessEqual(len(calls), articles_module._WEB_PAGE_COUNT_MAX_PROBES)
        self.assertEqual(len(calls), len(set(calls)))

    @patch("backend.articles.biz_to_book_id", return_value="book")
    @patch("backend.articles._discover_web_total_pages", return_value=37)
    def test_page_count_endpoint_returns_exact_total(self, discover, _book_id):
        response = self.client.get("/api/articles/page-count/account?count=20")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"total_pages": 37, "total_pages_exact": True})
        discover.assert_called_once_with("book", 20)

    @patch("backend.articles.account_pool.report")
    @patch(
        "backend.articles.borrow_weread_session",
        return_value=("account", "vid", "token", {"Cookie": "session"}),
    )
    @patch("backend.articles.biz_to_book_id", return_value="MP_WXS_3529992454")
    def test_web_history_source_expands_subreviews_and_keeps_deep_pagination(
        self,
        _book_id,
        _borrow,
        _report,
    ):
        opaque_id = (
            "MP_WXS_3529992454_"
            "WR1FAV44yAfhBDg8R5DajB6z2at3SoDs91Qh1rHDYi5xbB6X4mW88YFP81yf0c9E1r1wQEMZ2cz"
        )
        session = FakeWebSession(
            {
                "reviews": [
                    {
                        "createTime": 1717200000,
                        "subReviews": [
                            {
                                "reviewId": opaque_id,
                                "review": {
                                    "mpInfo": {
                                        "title": "2024 年历史文章",
                                        "content": "摘要",
                                        "mp_name": "冲击波前沿",
                                        "time": 1717200000,
                                        "pic_url": "https://example.com/cover.jpg",
                                    }
                                },
                            },
                            {
                                "reviewId": "MP_WXS_3529992454_oi~Lh3K0LZ92f~LtQBSljQ",
                                "review": {
                                    "mpInfo": {
                                        "title": "同次推送的第二篇",
                                        "time": 1717200001,
                                    }
                                },
                            },
                        ],
                    }
                ],
                "clearAll": 1,
            }
        )

        with patch("backend.articles.get_weread_session", return_value=session):
            result = articles_module._fetch_articles_page(
                "account",
                begin=140,
                count=20,
                account_name="冲击波前沿",
                with_meta=True,
            )

        rows, _total, can_continue, total_exact, continuation_exact = result
        self.assertEqual([row["title"] for row in rows], ["2024 年历史文章", "同次推送的第二篇"])
        self.assertIn("/api/wechat-mp/app/api/articles/open?review_id=", rows[0]["link"])
        self.assertEqual(
            rows[1]["link"],
            "https://mp.weixin.qq.com/s/oi_Lh3K0LZ92f_LtQBSljQ",
        )
        self.assertEqual(can_continue, 1)
        self.assertFalse(total_exact)
        self.assertFalse(continuation_exact)
        self.assertEqual(session.calls[0][1]["params"]["offset"], 140)

    @patch("backend.articles.account_pool.report")
    @patch(
        "backend.articles.borrow_weread_session",
        return_value=("account", "vid", "token", {"Cookie": "session"}),
    )
    def test_web_history_empty_page_is_exact_terminal(self, _borrow, _report):
        session = FakeWebSession({"reviews": [], "clearAll": 0})

        with patch("backend.articles.get_weread_session", return_value=session):
            result = articles_module._fetch_web_articles_page(
                "MP_WXS_3529992454",
                begin=500,
                count=20,
                account_name="冲击波前沿",
            )

        self.assertEqual(result, ([], 500, 0, False, True))

    @patch("backend.articles.account_pool.report")
    @patch(
        "backend.articles.borrow_weread_session",
        return_value=("account", "vid", "token", {"Cookie": "session"}),
    )
    def test_web_history_empty_batch_is_retried_before_cache(self, _borrow, _report):
        attempts = 0

        def payload(_offset):
            nonlocal attempts
            attempts += 1
            return {"reviews": []} if attempts == 1 else {"reviews": [{"subReviews": []}]}

        session = FakeWebSession(payload)
        with patch("backend.articles.get_weread_session", return_value=session):
            data = articles_module._fetch_web_history_batch("MP_WXS_3529992454", 80)

        self.assertEqual(len(data["reviews"]), 1)
        self.assertEqual(attempts, 2)
        self.assertIn(("MP_WXS_3529992454", 80), articles_module._web_history_cache)

    @patch("backend.articles.account_pool.report")
    @patch(
        "backend.articles.borrow_weread_session",
        return_value=("account", "vid", "token", {"Cookie": "session"}),
    )
    def test_web_history_multi_batch_does_not_stop_on_short_nonempty_batch(
        self,
        _borrow,
        _report,
    ):
        def group(index):
            return {
                "createTime": 1717200000 - index,
                "subReviews": [
                    {
                        "reviewId": f"MP_WXS_3529992454_article-{index:04d}-history",
                        "review": {"mpInfo": {"title": f"文章 {index}"}},
                    }
                ],
            }

        def payload(offset):
            size = 19 if offset == 20 else 20
            return {
                "reviews": [group(offset + index) for index in range(size)],
                "clearAll": 0,
            }

        session = FakeWebSession(payload)
        with patch("backend.articles.get_weread_session", return_value=session):
            rows, _total, can_continue, total_exact, continuation_exact = (
                articles_module._fetch_web_articles_page(
                    "MP_WXS_3529992454",
                    begin=0,
                    count=50,
                    account_name="冲击波前沿",
                )
            )

        self.assertEqual(len(rows), 49)
        self.assertEqual([call[1]["params"]["offset"] for call in session.calls], [0, 20, 40])
        self.assertEqual(can_continue, 1)
        self.assertFalse(total_exact)
        self.assertFalse(continuation_exact)

    def test_extracts_canonical_wechat_url_and_removes_chksm(self):
        raw_html = (
            '<meta property="og:url" '
            'content="https://mp.weixin.qq.com/s?__biz=abc&amp;mid=1&amp;idx=2&amp;chksm=unsafe">'
        )

        self.assertEqual(
            articles_module._canonical_url_from_weread_html(raw_html),
            "https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=2",
        )

    @patch("backend.downloader.fetch_via_weread_content")
    def test_open_article_resolves_opaque_review_id_and_redirects(self, fetch_content):
        review_id = (
            "MP_WXS_3529992454_"
            "WR1FAV44yAfhBDg8R5DajB6z2atFR7GQ19hmFuWCry2p9GEZ0qV3xn9seGf2BKQ7lbCq6B92FLz"
        )
        fetch_content.return_value = (
            '<meta property="og:url" '
            'content="https://mp.weixin.qq.com/s?__biz=abc&amp;mid=1&amp;idx=2">',
            True,
        )

        response = self.client.get(
            "/api/articles/open",
            query_string={"review_id": review_id},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            "https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=2",
        )
        fetch_content.assert_called_once_with(review_id)

    def test_explicit_pagination_and_total_are_respected(self):
        self.assertEqual(
            articles_module._parse_upstream_pagination(
                {"hasMore": False, "totalCount": 79},
                offset=60,
                returned_count=19,
            ),
            (False, True, 79),
        )
        self.assertEqual(
            articles_module._parse_upstream_pagination(
                {"pagination": {"can_continue": "1", "total_count": "101"}},
                offset=60,
                returned_count=19,
            ),
            (True, True, 101),
        )

    @patch("backend.articles.account_pool.report")
    @patch("backend.waterwall.detect_waterwall", return_value=None)
    @patch("backend.articles.borrow_weread_session", return_value=("account", "vid", "token", {}))
    @patch("backend.articles.biz_to_book_id", return_value="MP_WXS_3529992454")
    def test_fetch_short_realistic_page_does_not_stop_early(
        self,
        _book_id,
        _borrow,
        _waterwall,
        _report,
    ):
        rows = [
            {"reviewId": f"MP_WXS_3529992454_article-{index}", "title": f"文章 {index}"}
            for index in range(19)
        ]
        session = FakeSession({"data": rows})

        with patch("backend.articles.get_weread_session", return_value=session):
            result = articles_module._fetch_articles_page(
                "account",
                begin=60,
                count=20,
                with_meta=True,
            )

        articles, total, can_continue, total_exact, continuation_exact = result
        self.assertEqual(len(articles), 19)
        self.assertEqual(total, 80)
        self.assertEqual(can_continue, 1)
        self.assertFalse(total_exact)
        self.assertFalse(continuation_exact)

    @patch("backend.articles.account_pool.report")
    @patch("backend.waterwall.detect_waterwall", return_value=None)
    @patch("backend.articles.borrow_weread_session", return_value=("account", "vid", "token", {}))
    @patch("backend.articles.biz_to_book_id", return_value="MP_WXS_3529992454")
    def test_successful_empty_later_page_does_not_fallback_to_unpaged_list(
        self,
        _book_id,
        _borrow,
        _waterwall,
        _report,
    ):
        session = FakeSession({"data": []})

        with patch("backend.articles.get_weread_session", return_value=session):
            result = articles_module._fetch_articles_page(
                "account",
                begin=80,
                count=20,
                with_meta=True,
            )

        self.assertEqual(result, ([], 80, 0, False, True))
        self.assertFalse(any("/article/list" in url for url in session.urls))

    @patch("backend.articles.load_json")
    def test_download_states_cover_all_five_filters(self, load_json):
        load_json.return_value = [
            {"link": "https://mp.weixin.qq.com/s/downloaded", "success": True},
            {
                "link": "https://mp.weixin.qq.com/s/importing",
                "success": True,
                "download_state": "importing",
            },
            {
                "link": "https://mp.weixin.qq.com/s/imported",
                "success": True,
                "download_state": "imported",
            },
            {
                "link": "https://mp.weixin.qq.com/s/failed",
                "success": False,
                "failure_stage": "download",
                "error": "失败",
            },
        ]
        rows = [
            {"link": "https://mp.weixin.qq.com/s/not-downloaded"},
            {"link": "https://mp.weixin.qq.com/s/downloaded"},
            {"link": "https://mp.weixin.qq.com/s/importing"},
            {"link": "https://mp.weixin.qq.com/s/imported"},
            {"link": "https://mp.weixin.qq.com/s/failed"},
        ]

        articles_module._apply_article_download_states(rows)

        self.assertEqual(
            [row["download_state"] for row in rows],
            ["not_downloaded", "downloaded", "importing", "imported", "failed"],
        )
        self.assertEqual(rows[-1]["failure_stage"], "download")

    def test_disk_history_sync_discovers_markdown_only_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "前沿技术公众号" / "无人系统文章"
            artifact.mkdir(parents=True)
            (artifact / "无人系统文章.md").write_text("# 无人系统文章\n", encoding="utf-8")
            history = []

            with patch("backend.articles.get_settings", return_value={"download_dir": directory}):
                changed = articles_module._sync_history_from_disk(history)

            self.assertTrue(changed)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["title"], "无人系统文章")
            self.assertTrue(history[0]["has_markdown"])
            self.assertFalse(history[0]["has_pdf"])


if __name__ == "__main__":
    unittest.main()
