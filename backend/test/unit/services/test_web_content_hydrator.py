import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from platform_core.services import web_content_hydrator


@pytest.fixture(autouse=True)
def reset_hydration_runtime(monkeypatch):
    web_content_hydrator._HYDRATION_CACHE.clear()
    web_content_hydrator._HYDRATION_INFLIGHT.clear()
    web_content_hydrator._DOMAIN_STATE.clear()
    monkeypatch.setenv("WEB_SEARCH_HYDRATION_DOMAIN_DELAY_SECONDS", "0")
    monkeypatch.setenv("WEB_SEARCH_BROWSER_FALLBACK_ENABLED", "true")


class _Page:
    status = 200
    url = "https://www.navy.mil/research/auv"
    body = b""

    @staticmethod
    def markdown(*, main_content_only):
        assert main_content_only is True
        return "Low-cost expendable AUV shallow-water acoustic sensing evidence. " * 4


class _Fetcher:
    calls = []

    @classmethod
    def get(cls, url, **kwargs):
        cls.calls.append((url, kwargs))
        return _Page()


def test_scrapling_hydration_resolves_redirect_and_enriches_content(monkeypatch):
    monkeypatch.setattr(web_content_hydrator, "_load_scrapling_fetcher", lambda: _Fetcher)
    _Fetcher.calls.clear()

    results = web_content_hydrator.hydrate_search_results(
        [
            {
                "title": "Mass production attritable AUV",
                "url": "http://www.baidu.com/link?url=opaque",
                "content": "short snippet",
            }
        ]
    )

    item = results[0]
    assert item["url"] == "https://www.navy.mil/research/auv"
    assert item["site_name"] == "www.navy.mil"
    assert item["search_redirect_url"].startswith("http://www.baidu.com/link")
    assert item["content_hydrator"] == "scrapling"
    assert item["content_level"] == "web_page"
    assert item["hydration_mode"] == "http"
    assert "shallow-water acoustic" in item["content"]
    assert _Fetcher.calls[0][1]["follow_redirects"] is False
    assert _Fetcher.calls[1][1]["follow_redirects"] == "safe"
    assert _Fetcher.calls[0][1]["retries"] == 1


def test_search_redirect_survives_target_body_timeout(monkeypatch):
    class RedirectPage:
        status = 302
        url = "http://www.baidu.com/link?url=opaque"
        headers = {"Location": "https://example.org/large-report"}

    class RedirectThenTimeoutFetcher:
        calls = 0

        @classmethod
        def get(cls, *_args, **_kwargs):
            cls.calls += 1
            if cls.calls == 1:
                return RedirectPage()
            raise TimeoutError("target body timed out")

    monkeypatch.setattr(
        web_content_hydrator,
        "_load_scrapling_fetcher",
        lambda: RedirectThenTimeoutFetcher,
    )

    results = web_content_hydrator.hydrate_search_results(
        [{"title": "report", "url": "http://www.baidu.com/link?url=opaque", "content": "snippet"}]
    )

    assert results[0]["url"] == "https://example.org/large-report"
    assert results[0]["search_redirect_url"].startswith("http://www.baidu.com/link")
    assert results[0]["content_hydrator"] == "scrapling"
    assert results[0]["hydration_mode"] == "redirect_only"


def test_scrapling_hydration_is_failure_isolated_and_rejects_private_targets(monkeypatch):
    class FailingFetcher:
        @staticmethod
        def get(*_args, **_kwargs):
            raise RuntimeError("blocked")

    monkeypatch.setattr(web_content_hydrator, "_load_scrapling_fetcher", lambda: FailingFetcher)
    source = [
        {"title": "public", "url": "https://example.org/report", "content": "snippet"},
        {"title": "private", "url": "http://127.0.0.1/admin", "content": "do not fetch"},
    ]

    results = web_content_hydrator.hydrate_search_results(source)

    assert results[0]["content"] == "snippet"
    assert results[0]["hydration_rejected_reason"] == "fetch_error"
    assert results[1] == source[1]


def test_dynamic_shell_upgrades_only_selected_page_to_stealth_browser(monkeypatch):
    class ShellPage:
        status = 200
        url = "https://example.org/app"
        body = b'<html><body><div id="root"></div><script>' + b"x" * 400 + b"</script></body></html>"

        @staticmethod
        def markdown(*, main_content_only):
            assert main_content_only is True
            return "Loading"

    class BrowserPage:
        status = 200
        url = "https://example.org/app"
        body = b""

        @staticmethod
        def markdown(*, main_content_only):
            assert main_content_only is True
            return "Dynamic app rendered primary-source evidence with conditions and limitations. " * 4

    class FastFetcher:
        @staticmethod
        def get(*_args, **_kwargs):
            return ShellPage()

    class BrowserFetcher:
        calls = []

        @classmethod
        def fetch(cls, url, **kwargs):
            cls.calls.append((url, kwargs))
            return BrowserPage()

    monkeypatch.setattr(web_content_hydrator, "_load_scrapling_fetcher", lambda: FastFetcher)
    monkeypatch.setattr(web_content_hydrator, "_load_scrapling_stealthy_fetcher", lambda: BrowserFetcher)

    result = web_content_hydrator.hydrate_search_results(
        [{"title": "dynamic", "url": "https://example.org/app", "content": "snippet"}]
    )[0]

    assert result["hydration_mode"] == "browser"
    assert result["content_level"] == "web_page"
    assert "rendered primary-source" in result["content"]
    assert BrowserFetcher.calls[0][1]["block_ads"] is True
    assert BrowserFetcher.calls[0][1]["solve_cloudflare"] is False
    assert BrowserFetcher.calls[0][1]["disable_resources"] is True


def test_challenge_page_uses_cloudflare_browser_mode_but_rate_limit_does_not(monkeypatch):
    class ChallengePage:
        status = 403
        url = "https://protected.example/report"
        body = b"<html>Just a moment... cf-chl-turnstile</html>"

        @staticmethod
        def markdown(*, main_content_only):
            return "Just a moment"

    class BrowserPage:
        status = 200
        url = "https://protected.example/report"
        body = b""

        @staticmethod
        def markdown(*, main_content_only):
            return "Protected public report content recovered after the passive challenge. " * 4

    class FastFetcher:
        @staticmethod
        def get(*_args, **_kwargs):
            return ChallengePage()

    class BrowserFetcher:
        kwargs = None

        @classmethod
        def fetch(cls, _url, **kwargs):
            cls.kwargs = kwargs
            return BrowserPage()

    monkeypatch.setattr(web_content_hydrator, "_load_scrapling_fetcher", lambda: FastFetcher)
    monkeypatch.setattr(web_content_hydrator, "_load_scrapling_stealthy_fetcher", lambda: BrowserFetcher)

    result = web_content_hydrator.hydrate_search_results(
        [{"title": "protected", "url": "https://protected.example/report", "content": "snippet"}]
    )[0]

    assert result["hydration_mode"] == "browser"
    assert BrowserFetcher.kwargs["solve_cloudflare"] is True
    assert BrowserFetcher.kwargs["disable_resources"] is False

    ChallengePage.status = 429
    web_content_hydrator._HYDRATION_CACHE.clear()
    BrowserFetcher.kwargs = None
    result = web_content_hydrator.hydrate_search_results(
        [{"title": "limited", "url": "https://protected.example/limited", "content": "snippet"}]
    )[0]
    assert result["hydration_mode"] == "http"
    assert BrowserFetcher.kwargs is None


def test_rag_markdown_failure_falls_back_to_sanitized_html_and_cache(monkeypatch):
    class InvalidMarkupPage:
        status = 200
        url = "https://example.org/report"
        body = b"<article>Validated report\x00 evidence with operating conditions and limitations.</article>"
        encoding = "utf-8"

        @staticmethod
        def markdown(*, main_content_only):
            raise ValueError("invalid XML control character")

    class Fetcher:
        calls = 0

        @classmethod
        def get(cls, *_args, **_kwargs):
            cls.calls += 1
            return InvalidMarkupPage()

    monkeypatch.setenv("WEB_SEARCH_HYDRATION_MIN_CONTENT_CHARS", "40")
    monkeypatch.setattr(web_content_hydrator, "_load_scrapling_fetcher", lambda: Fetcher)
    source = [{"title": "report", "url": "https://example.org/report", "content": "short"}]

    first = web_content_hydrator.hydrate_search_results(source)[0]
    second = web_content_hydrator.hydrate_search_results(source)[0]

    assert "Validated report evidence" in first["content"]
    assert "\x00" not in first["content"]
    assert second["hydration_cache_hit"] is True
    assert Fetcher.calls == 1


def test_hydration_rejects_unrelated_or_non_html_pages(monkeypatch):
    class UnrelatedPage:
        status = 200
        url = "https://example.org/login"
        body = b""
        headers = {"Content-Type": "text/html; charset=utf-8"}

        @staticmethod
        def markdown(*, main_content_only):
            return "Account login cookies privacy portal navigation. " * 8

    class PdfPage:
        status = 200
        url = "https://example.org/report.pdf"
        body = b"%PDF-1.7 binary"
        headers = {"Content-Type": "application/pdf"}

        @staticmethod
        def markdown(*, main_content_only):
            return "Radar report extracted from binary content. " * 8

    class Fetcher:
        @staticmethod
        def get(url, **_kwargs):
            return PdfPage() if url.endswith(".pdf") else UnrelatedPage()

    monkeypatch.setattr(web_content_hydrator, "_load_scrapling_fetcher", lambda: Fetcher)
    source = [
        {"title": "Radar field experiment", "url": "https://example.org/paper", "content": "trusted snippet"},
        {"title": "Radar report", "url": "https://example.org/report.pdf", "content": "pdf snippet"},
    ]

    results = web_content_hydrator.hydrate_search_results(source)

    assert results[0]["content"] == "trusted snippet"
    assert results[0]["hydration_rejected_reason"] == "identity_mismatch"
    assert results[1]["content"] == "pdf snippet"
    assert results[1]["hydration_rejected_reason"] == "content_type"
    assert all("content_level" not in item for item in results)


def test_hydration_limit_and_single_flight_avoid_duplicate_fetches(monkeypatch):
    class Page:
        status = 200
        url = "https://example.org/report"
        body = b""

        @staticmethod
        def markdown(*, main_content_only):
            return "Verified report evidence with operating conditions and limitations. " * 4

    class Fetcher:
        calls = 0

        @classmethod
        def get(cls, *_args, **_kwargs):
            cls.calls += 1
            time.sleep(0.05)
            return Page()

    monkeypatch.setenv("WEB_SEARCH_HYDRATION_MAX_RESULTS", "1")
    monkeypatch.setattr(web_content_hydrator, "_load_scrapling_fetcher", lambda: Fetcher)
    source = [
        {"title": "Verified report", "url": "https://example.org/report", "content": "snippet"},
        {"title": "Second report", "url": "https://example.org/second", "content": "second snippet"},
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: web_content_hydrator.hydrate_search_results(source), range(2)))

    assert Fetcher.calls == 1
    assert first[0]["content_level"] == "web_page"
    assert second[0]["content_level"] == "web_page"
    assert first[1] == second[1] == source[1]
    assert first[0].get("hydration_cache_hit") or second[0].get("hydration_cache_hit")


def test_hydration_total_budget_preserves_snippet_and_reports_rejection(monkeypatch):
    class SlowFetcher:
        @staticmethod
        def get(*_args, **_kwargs):
            time.sleep(0.1)
            return _Page()

    policy = replace(web_content_hydrator._load_policy(), total_timeout_seconds=0.02)
    monkeypatch.setattr(web_content_hydrator, "_load_policy", lambda: policy)
    monkeypatch.setattr(web_content_hydrator, "_load_scrapling_fetcher", lambda: SlowFetcher)

    started = time.monotonic()
    result = web_content_hydrator.hydrate_search_results(
        [{"title": "Verified report", "url": "https://example.org/report", "content": "trusted snippet"}]
    )[0]

    assert time.monotonic() - started < 0.08
    assert result["content"] == "trusted snippet"
    assert result["hydration_rejected_reason"] == "budget_exhausted"
