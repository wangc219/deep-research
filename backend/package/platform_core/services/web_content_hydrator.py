"""用 Scrapling 为搜索结果补充可引用正文，并有界升级动态页面抓取。"""

from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from platform_core.utils import logger

_BROWSER_SEMAPHORE = threading.BoundedSemaphore(1)
_STATE_LOCK = threading.Lock()
_HYDRATION_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_HYDRATION_INFLIGHT: dict[str, threading.Event] = {}
_DOMAIN_STATE: dict[str, dict[str, float]] = {}
_CACHE_FIELDS = (
    "url",
    "site_name",
    "search_redirect_url",
    "content",
    "content_hydrator",
    "content_level",
    "hydration_mode",
    "hydration_verified",
    "hydration_rejected_reason",
)
_CHALLENGE_MARKERS = (
    "captcha",
    "cf-chl-",
    "challenge-platform",
    "cloudflare ray id",
    "enable javascript and cookies to continue",
    "just a moment",
    "please verify you are a human",
    "security verification",
    "turnstile",
    "unusual traffic",
    "访问验证",
    "安全验证",
    "验证码",
)
_DYNAMIC_SHELL_MARKERS = (
    "__next_data__",
    "__nuxt__",
    "data-reactroot",
    'id="app"',
    'id="root"',
    "javascript is required",
    "please enable javascript",
)


@dataclass(frozen=True, slots=True)
class _HydrationPolicy:
    timeout_seconds: float
    total_timeout_seconds: float
    browser_timeout_ms: int
    content_chars: int
    minimum_content_chars: int
    browser_fallback_enabled: bool
    browser_fallback_results: int
    cache_seconds: int
    domain_delay_seconds: float
    domain_max_delay_seconds: float


class _BrowserBudget:
    """让一次搜索最多升级少量高价值页面，避免浏览器扇出。"""

    def __init__(self, remaining: int):
        self.remaining = remaining
        self._lock = threading.Lock()

    def reserve(self) -> bool:
        with self._lock:
            if self.remaining <= 0:
                return False
            self.remaining -= 1
            return True


def hydrate_search_results(
    results: list[dict[str, Any]],
    *,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    """并发补充候选页；HTTP 不足时仅对少量页面升级隐蔽浏览器。"""
    if not _enabled() or not results:
        return results

    policy = _load_policy()
    configured_limit = _integer_env("WEB_SEARCH_HYDRATION_MAX_RESULTS", 6, 1, 12)
    requested_limit = configured_limit if max_results is None else max(1, int(max_results))
    limit = min(len(results), configured_limit, requested_limit)
    selected = [dict(item) for item in results[:limit]]
    workers = min(len(selected), _integer_env("WEB_SEARCH_HYDRATION_CONCURRENCY", 4, 1, 8))

    try:
        fetcher = _load_scrapling_fetcher()
    except ImportError as exc:
        logger.warning(f"Scrapling search hydration disabled because dependency is unavailable: {exc}")
        return results

    browser_budget = _BrowserBudget(policy.browser_fallback_results if policy.browser_fallback_enabled else 0)
    hydrated: dict[int, dict[str, Any]] = {}
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="search-hydration")
    futures = {
        executor.submit(_hydrate_one, item, fetcher, browser_budget, policy): index
        for index, item in enumerate(selected)
    }
    done, pending = wait(futures, timeout=policy.total_timeout_seconds)
    for future in done:
        index = futures[future]
        try:
            hydrated[index] = future.result()
        except Exception as exc:  # noqa: BLE001 - 单页失败不能拖垮整次检索
            logger.debug(f"Scrapling search hydration failed: {type(exc).__name__}: {str(exc)[:200]}")
            hydrated[index] = _rejected_result(selected[index], "fetch_error")
    for future in pending:
        future.cancel()
        hydrated[futures[future]] = _rejected_result(selected[futures[future]], "budget_exhausted")
    executor.shutdown(wait=False, cancel_futures=True)

    return [hydrated.get(index, item) for index, item in enumerate(selected)] + [dict(item) for item in results[limit:]]


def _hydrate_one(
    item: dict[str, Any],
    fetcher: Any,
    browser_budget: _BrowserBudget,
    policy: _HydrationPolicy,
) -> dict[str, Any]:
    """合并同 URL 并发抓取，避免 Open WebSearch 与 SearXNG 重复访问。"""
    if item.get("hydration_verified") is True and item.get("content_level") == "web_page":
        return item

    url = str(item.get("url") or "").strip()
    if not _is_public_http_url(url):
        return item

    cached = _cached_patch(url)
    if cached is not None:
        return {**item, **cached, "hydration_cache_hit": True}

    owner, event = _claim_hydration(url)
    if not owner:
        event.wait(timeout=policy.timeout_seconds + 0.5)
        cached = _cached_patch(url)
        return {**item, **cached, "hydration_cache_hit": True} if cached is not None else item

    try:
        return _hydrate_uncached(item, fetcher, browser_budget, policy)
    finally:
        _finish_hydration(url, event)


def _hydrate_uncached(
    item: dict[str, Any],
    fetcher: Any,
    browser_budget: _BrowserBudget,
    policy: _HydrationPolicy,
) -> dict[str, Any]:
    """优先快速 HTTP 抓取，只有挑战页或动态空壳才升级浏览器。"""
    url = str(item.get("url") or "").strip()

    enriched = dict(item)
    fetch_url = url
    if _is_search_redirect_url(url):
        try:
            _wait_for_domain(url, policy)
            redirect_page = fetcher.get(
                url,
                follow_redirects=False,
                timeout=min(3.0, policy.timeout_seconds),
                retries=1,
                impersonate="chrome",
                stealthy_headers=True,
            )
            resolved_url = _resolved_redirect_url(url, redirect_page)
            if resolved_url != url:
                _apply_resolved_url(enriched, url, resolved_url)
                fetch_url = resolved_url
        except Exception as exc:  # noqa: BLE001 - 预解析失败后仍可尝试原链路
            logger.debug(f"Search redirect preflight failed: {type(exc).__name__}: {str(exc)[:200]}")

    try:
        _wait_for_domain(fetch_url, policy)
        page = fetcher.get(
            fetch_url,
            follow_redirects="safe",
            timeout=policy.timeout_seconds,
            retries=2,
            retry_delay=0.25,
            impersonate=["chrome", "firefox", "safari"],
            stealthy_headers=True,
            selector_config={"huge_tree": True},
        )
    except Exception:
        if fetch_url != url:
            enriched["content_hydrator"] = "scrapling"
            enriched["hydration_mode"] = "redirect_only"
            _store_patch(url, item, enriched, policy.cache_seconds)
            return enriched
        raise

    final_url = str(getattr(page, "url", "") or fetch_url).strip()
    if not _is_public_http_url(final_url):
        final_url = fetch_url
    if final_url != url:
        _apply_resolved_url(enriched, url, final_url)

    status = int(getattr(page, "status", 0) or 0)
    markdown = _safe_page_markdown(page)
    challenge = _is_challenge_page(page, markdown)
    _record_domain_result(final_url, status, challenge, policy)

    browser_reason = (
        "challenge" if challenge and status != 429 else "dynamic_shell" if _is_dynamic_shell(page, markdown) else ""
    )
    if browser_reason and browser_budget.reserve():
        browser_page = _browser_fetch(final_url, challenge=browser_reason == "challenge", policy=policy)
        if browser_page is not None:
            browser_markdown = _safe_page_markdown(browser_page)
            if len(browser_markdown) > len(markdown):
                page = browser_page
                markdown = browser_markdown
                status = int(getattr(page, "status", 0) or 0)
                final_url = str(getattr(page, "url", "") or final_url).strip()
                if _is_public_http_url(final_url) and final_url != url:
                    _apply_resolved_url(enriched, url, final_url)
                enriched["hydration_mode"] = "browser"

    rejection = ""
    if not 200 <= status < 400:
        rejection = "http_status"
    elif not _page_supports_markdown(page):
        rejection = "content_type"
    elif len(markdown) < policy.minimum_content_chars:
        rejection = "insufficient_content"
    elif not _page_matches_search_result(item, markdown):
        rejection = "identity_mismatch"

    if not rejection:
        original = _normalize_text(enriched.get("content"))
        if len(markdown) >= len(original):
            enriched["content"] = markdown[: policy.content_chars]
            enriched["content_level"] = "web_page"
            enriched["hydration_verified"] = True
        else:
            rejection = "not_more_complete"
    if rejection:
        enriched["hydration_rejected_reason"] = rejection
    enriched["content_hydrator"] = "scrapling"
    enriched.setdefault("hydration_mode", "http")
    _store_patch(url, item, enriched, policy.cache_seconds)
    return enriched


def _browser_fetch(url: str, *, challenge: bool, policy: _HydrationPolicy) -> Any | None:
    """串行执行昂贵浏览器升级；不可用时保留 HTTP 结果。"""
    try:
        stealthy_fetcher = _load_scrapling_stealthy_fetcher()
    except ImportError as exc:
        logger.debug(f"Scrapling browser fallback unavailable: {exc}")
        return None

    if not _BROWSER_SEMAPHORE.acquire(blocking=False):
        return None
    try:
        try:
            return stealthy_fetcher.fetch(
                url,
                headless=True,
                timeout=policy.browser_timeout_ms,
                retries=1,
                block_ads=True,
                disable_resources=not challenge,
                network_idle=False,
                google_search=False,
                solve_cloudflare=challenge,
                selector_config={"huge_tree": True},
            )
        except Exception as exc:  # noqa: BLE001 - 浏览器是增强路径，失败不得污染搜索主链
            logger.debug(f"Scrapling browser fallback failed: {type(exc).__name__}: {str(exc)[:200]}")
            return None
    finally:
        _BROWSER_SEMAPHORE.release()


def _safe_page_markdown(page: Any) -> str:
    """优先使用 RAG Markdown；异常 HTML 退回清洗文本，避免控制字符拖垮整页。"""
    try:
        markdown = page.markdown(main_content_only=True)
    except (RecursionError, TypeError, ValueError):
        raw = _page_body_text(page)
        try:
            markdown = BeautifulSoup(_strip_xml_controls(raw), "html.parser").get_text(" ", strip=True)
        except (RecursionError, TypeError, ValueError):
            markdown = _strip_xml_controls(raw)
    return _normalize_text(markdown)


def _page_body_text(page: Any) -> str:
    body = getattr(page, "body", b"") or b""
    if isinstance(body, bytes):
        encoding = str(getattr(page, "encoding", "") or "utf-8")
        try:
            return body.decode(encoding, errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")
    return str(body)


def _is_challenge_page(page: Any, markdown: str) -> bool:
    status = int(getattr(page, "status", 0) or 0)
    detail = f"{markdown} {_page_body_text(page)[:6000]}".casefold()
    return (
        status in {403, 503}
        or (status not in {200, 204} and any(marker in detail for marker in _CHALLENGE_MARKERS))
        or (len(markdown) < 300 and any(marker in detail for marker in _CHALLENGE_MARKERS))
    )


def _is_dynamic_shell(page: Any, markdown: str) -> bool:
    if len(markdown) >= 160:
        return False
    body = _page_body_text(page).casefold()
    return len(body) >= 300 and any(marker in body for marker in _DYNAMIC_SHELL_MARKERS)


def _wait_for_domain(url: str, policy: _HydrationPolicy) -> None:
    """对同域请求设置进程内自适应间隔，避免并发探索员集中冲击站点。"""
    host = (urlparse(url).hostname or "").casefold()
    if not host:
        return
    with _STATE_LOCK:
        state = _DOMAIN_STATE.setdefault(host, {"delay": policy.domain_delay_seconds, "next_start": 0.0})
        wait_seconds = max(0.0, state["next_start"] - time.monotonic())
        state["next_start"] = max(state["next_start"], time.monotonic()) + state["delay"]
    if wait_seconds:
        time.sleep(min(wait_seconds, policy.domain_max_delay_seconds))


def _record_domain_result(url: str, status: int, challenge: bool, policy: _HydrationPolicy) -> None:
    """阻塞时指数退避，健康响应后逐步恢复基础间隔。"""
    host = (urlparse(url).hostname or "").casefold()
    if not host:
        return
    with _STATE_LOCK:
        state = _DOMAIN_STATE.setdefault(host, {"delay": policy.domain_delay_seconds, "next_start": 0.0})
        if challenge or status in {429, 503}:
            state["delay"] = min(
                policy.domain_max_delay_seconds,
                max(policy.domain_delay_seconds, state["delay"] * 2),
            )
        elif 200 <= status < 400:
            state["delay"] = max(policy.domain_delay_seconds, state["delay"] * 0.75)


def _cached_patch(url: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _STATE_LOCK:
        cached = _HYDRATION_CACHE.get(url)
        if cached is None:
            return None
        expires_at, patch = cached
        if expires_at <= now:
            _HYDRATION_CACHE.pop(url, None)
            return None
        return dict(patch)


def _claim_hydration(url: str) -> tuple[bool, threading.Event]:
    """让并行检索通道对同一 URL 只执行一次真实抓取。"""
    with _STATE_LOCK:
        event = _HYDRATION_INFLIGHT.get(url)
        if event is not None:
            return False, event
        event = threading.Event()
        _HYDRATION_INFLIGHT[url] = event
        return True, event


def _finish_hydration(url: str, event: threading.Event) -> None:
    with _STATE_LOCK:
        if _HYDRATION_INFLIGHT.get(url) is event:
            _HYDRATION_INFLIGHT.pop(url, None)
        event.set()


def _store_patch(
    cache_key: str,
    original: dict[str, Any],
    enriched: dict[str, Any],
    cache_seconds: int,
) -> None:
    patch = {
        field: enriched[field]
        for field in _CACHE_FIELDS
        if field in enriched and enriched.get(field) != original.get(field)
    }
    if not patch or cache_seconds <= 0:
        return
    with _STATE_LOCK:
        if len(_HYDRATION_CACHE) >= 512:
            oldest = min(_HYDRATION_CACHE, key=lambda key: _HYDRATION_CACHE[key][0])
            _HYDRATION_CACHE.pop(oldest, None)
        _HYDRATION_CACHE[cache_key] = (time.monotonic() + cache_seconds, patch)


def _rejected_result(item: dict[str, Any], reason: str) -> dict[str, Any]:
    """为抓取异常和总预算截止保留搜索摘要与可审计原因。"""
    return {
        **item,
        "content_hydrator": "scrapling",
        "hydration_mode": "http",
        "hydration_rejected_reason": reason,
    }


def _is_search_redirect_url(value: str) -> bool:
    """仅对常见搜索跳转入口做无跟随预解析。"""
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.rstrip("/").casefold()
    return bool(
        (hostname == "baidu.com" or hostname.endswith(".baidu.com"))
        and path == "/link"
        or (hostname == "sogou.com" or hostname.endswith(".sogou.com"))
        and path in {"/link", "/web/link"}
        or (hostname == "google.com" or hostname.endswith(".google.com"))
        and path == "/url"
    )


def _resolved_redirect_url(original_url: str, page: Any) -> str:
    """从无跟随响应的 Location 或抓取器最终地址中提取公开目标。"""
    headers = getattr(page, "headers", None) or {}
    location = ""
    if hasattr(headers, "items"):
        location = next(
            (str(value).strip() for key, value in headers.items() if str(key).casefold() == "location"),
            "",
        )
    candidate = urljoin(original_url, location) if location else str(getattr(page, "url", "") or "").strip()
    return candidate if candidate != original_url and _is_public_http_url(candidate) else original_url


def _apply_resolved_url(enriched: dict[str, Any], original_url: str, resolved_url: str) -> None:
    enriched["search_redirect_url"] = original_url
    enriched["url"] = resolved_url
    enriched["site_name"] = (urlparse(resolved_url).hostname or "").casefold()


def _load_scrapling_fetcher():
    """延迟导入快速 HTTP 抓取器。"""
    from scrapling.fetchers import Fetcher

    return Fetcher


def _load_scrapling_stealthy_fetcher():
    """延迟导入浏览器抓取器，避免普通搜索承担浏览器启动成本。"""
    from scrapling.fetchers import StealthyFetcher

    return StealthyFetcher


def _is_public_http_url(value: str) -> bool:
    """拒绝显式本地或私网目标；重定向再由 Scrapling safe 模式复核。"""
    try:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        return False
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        address = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        return True
    return bool(address.is_global)


def _strip_xml_controls(value: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", value)


def _normalize_text(value: object) -> str:
    return " ".join(_strip_xml_controls(str(value or "")).split())


def _page_supports_markdown(page: Any) -> bool:
    """拒绝 PDF、图片、压缩包等不应按 HTML Markdown 处理的响应。"""
    body = getattr(page, "body", b"") or b""
    if isinstance(body, bytes) and body.lstrip().startswith(b"%PDF-"):
        return False
    headers = getattr(page, "headers", None) or {}
    content_type = ""
    if hasattr(headers, "items"):
        content_type = next(
            (str(value).casefold() for key, value in headers.items() if str(key).casefold() == "content-type"),
            "",
        )
    return not content_type or any(
        value in content_type for value in ("text/html", "application/xhtml+xml", "text/plain")
    )


def _page_matches_search_result(item: dict[str, Any], markdown: str) -> bool:
    """用搜索题名锚点阻止主页、登录页和软阻塞页覆盖真实摘要。"""
    title = _normalize_text(item.get("title")).casefold()
    content = markdown.casefold()
    normalized_title = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", title)
    normalized_content = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", content)
    if len(normalized_title) >= 8 and normalized_title in normalized_content:
        return True

    ignored = {
        "about",
        "analysis",
        "based",
        "from",
        "latest",
        "official",
        "research",
        "study",
        "system",
        "using",
        "with",
    }
    latin_terms = {token for token in re.findall(r"[a-z0-9][a-z0-9.+/-]{2,}", title) if token not in ignored}
    if latin_terms and any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", content) for term in latin_terms):
        return True

    han = "".join(re.findall(r"[\u3400-\u9fff]+", title))
    han_pairs = {han[index : index + 2] for index in range(len(han) - 1)}
    return bool(han_pairs and sum(pair in content for pair in han_pairs) >= min(2, len(han_pairs)))


def _load_policy() -> _HydrationPolicy:
    return _HydrationPolicy(
        timeout_seconds=_float_env("WEB_SEARCH_HYDRATION_TIMEOUT_SECONDS", 6.0, 2.0, 15.0),
        total_timeout_seconds=_float_env("WEB_SEARCH_HYDRATION_TOTAL_SECONDS", 12.0, 2.0, 30.0),
        browser_timeout_ms=_integer_env("WEB_SEARCH_BROWSER_TIMEOUT_MS", 15_000, 5_000, 45_000),
        content_chars=_integer_env("WEB_SEARCH_HYDRATION_CONTENT_CHARS", 6_000, 1_000, 12_000),
        minimum_content_chars=_integer_env("WEB_SEARCH_HYDRATION_MIN_CONTENT_CHARS", 120, 40, 500),
        browser_fallback_enabled=_boolean_env("WEB_SEARCH_BROWSER_FALLBACK_ENABLED", True),
        browser_fallback_results=_integer_env("WEB_SEARCH_BROWSER_FALLBACK_RESULTS", 1, 0, 4),
        cache_seconds=_integer_env("WEB_SEARCH_HYDRATION_CACHE_SECONDS", 900, 0, 3600),
        domain_delay_seconds=_float_env("WEB_SEARCH_HYDRATION_DOMAIN_DELAY_SECONDS", 0.25, 0.0, 3.0),
        domain_max_delay_seconds=_float_env("WEB_SEARCH_HYDRATION_DOMAIN_MAX_DELAY_SECONDS", 4.0, 0.5, 30.0),
    )


def _enabled() -> bool:
    return _boolean_env("WEB_SEARCH_HYDRATION_ENABLED", True)


def _boolean_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() not in {"0", "false", "no", "off"}


def _integer_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))
