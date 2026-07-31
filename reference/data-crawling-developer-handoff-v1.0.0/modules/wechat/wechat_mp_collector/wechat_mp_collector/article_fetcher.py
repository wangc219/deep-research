from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 "
    "Mobile/15E148 Safari/604.1"
)

BLOCK_TEXTS = {
    "current environment verification": "当前环境异常，完成验证后即可继续访问",
    "deleted": "该内容已被发布者删除",
    "deleted_en": "The content has been deleted by the author.",
    "reviewing": "内容审核中",
    "unavailable": "该内容暂时无法查看",
    "violation": "违规无法查看",
    "violation_en": "Unable to view this content because it violates regulation",
    "send_failed": "发送失败无法查看",
}


class ArticleFetcher:
    def __init__(
        self,
        session_data: dict[str, Any] | None = None,
        *,
        browser_type: str = "webkit",
        headless: bool = True,
        timeout_ms: int = 30_000,
    ) -> None:
        self.session_data = session_data or {}
        self.browser_type = browser_type
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "ArticleFetcher":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def start(self) -> None:
        if self._browser:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, self.browser_type)
        self._browser = await launcher.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            user_agent=MOBILE_UA,
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
        )
        cookies = _cookies_for_playwright(self.session_data.get("cookies") or [])
        if cookies:
            try:
                await self._context.add_cookies(cookies)
            except Exception:
                pass

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def fetch(self, url: str) -> dict[str, Any]:
        if not self._context:
            await self.start()
        page = await self._context.new_page()
        info = {
            "url": url,
            "title": "",
            "author": "",
            "description": "",
            "topic_image": "",
            "publish_time": 0,
            "content_html": "",
            "content_markdown": "",
            "mp_name": "",
            "biz": "",
            "fetch_error": "",
        }
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            body_text = await _body_text(page)
            for message in BLOCK_TEXTS.values():
                if message in body_text:
                    info["fetch_error"] = message
                    return info

            await _scroll_and_fix_lazy_images(page)
            content_html = await page.evaluate(
                """() => {
                    const root = document.querySelector('#js_content')
                        || document.querySelector('#js_article')
                        || document.body;
                    return root ? root.innerHTML : '';
                }"""
            )
            content_html = clean_article_html(content_html or "")

            info.update(
                {
                    "title": await _meta(page, 'meta[property="og:title"]') or await page.title(),
                    "author": await _meta(page, 'meta[property="og:article:author"]'),
                    "description": await _meta(page, 'meta[property="og:description"]'),
                    "topic_image": await _meta(page, 'meta[property="twitter:image"]')
                    or await _meta(page, 'meta[property="og:image"]'),
                    "publish_time": await _publish_time(page),
                    "content_html": content_html,
                    "content_markdown": html_to_markdown(content_html),
                    "mp_name": await _mp_name(page),
                    "biz": await _biz(page, url, content_html),
                }
            )
            return info
        except Exception as exc:
            info["fetch_error"] = str(exc)
            return info
        finally:
            await page.close()


def clean_article_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["script", "style", "link"]):
        tag.decompose()

    for img in soup.find_all("img"):
        data_src = img.get("data-src")
        src = img.get("src")
        if data_src and (not src or str(src).startswith("data:")):
            img["src"] = data_src
        keep = {}
        for attr in ["src", "alt", "title", "style", "width", "height"]:
            value = img.get(attr)
            if value:
                keep[attr] = value
        img.attrs = keep

    return str(soup).strip()


def html_to_markdown(html: str) -> str:
    try:
        from markdownify import markdownify as md

        return md(html or "", heading_style="ATX", bullets="-").strip()
    except Exception:
        soup = BeautifulSoup(html or "", "html.parser")
        return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())


async def _body_text(page: Any) -> str:
    try:
        return await page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return ""


async def _meta(page: Any, selector: str) -> str:
    try:
        value = await page.evaluate(
            "(selector) => document.querySelector(selector)?.getAttribute('content') || ''",
            selector,
        )
        return str(value or "").strip()
    except Exception:
        return ""


async def _mp_name(page: Any) -> str:
    selectors = [
        "#js_wx_follow_nickname",
        "#profileBt .profile_nickname",
        'meta[property="og:article:author"]',
    ]
    for selector in selectors:
        try:
            if selector.startswith("meta"):
                value = await _meta(page, selector)
            else:
                value = await page.evaluate(
                    "(selector) => document.querySelector(selector)?.textContent || ''",
                    selector,
                )
            if value:
                return str(value).strip()
        except Exception:
            continue
    return ""


async def _biz(page: Any, url: str, content_html: str) -> str:
    try:
        value = await page.evaluate("() => window.biz || ''")
        if value:
            return str(value)
    except Exception:
        pass
    for text in [url, content_html, await _safe_content(page)]:
        match = re.search(r"(?:[?&]__biz=|var\s+biz\s*=\s*[\"'])([^&\"']+)", text or "")
        if match:
            return match.group(1)
    return ""


async def _publish_time(page: Any) -> int:
    try:
        text = await page.evaluate("() => document.querySelector('#publish_time')?.textContent || ''")
        timestamp = parse_publish_time(str(text).strip())
        if timestamp:
            return timestamp
        content = await _safe_content(page)
        for pattern in [
            r"publish_time\s*=\s*[\"']([^\"']+)[\"']",
            r"create_time\s*=\s*[\"']([^\"']+)[\"']",
        ]:
            match = re.search(pattern, content)
            if match:
                timestamp = parse_publish_time(match.group(1))
                if timestamp:
                    return timestamp
    except Exception:
        pass
    return 0


def parse_publish_time(value: str) -> int:
    value = (value or "").strip()
    if not value:
        return 0
    normalized = re.sub(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        lambda m: f"{m.group(1)}年{m.group(2).zfill(2)}月{m.group(3).zfill(2)}日",
        value,
    )
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y年%m月%d日 %H:%M",
        "%Y年%m月%d日",
        "%m月%d日",
    ]:
        try:
            if fmt == "%m月%d日":
                current = datetime.now()
                parsed = datetime.strptime(f"{current.year}年{normalized}", "%Y年%m月%d日")
                if parsed > current:
                    parsed = parsed.replace(year=current.year - 1)
            else:
                parsed = datetime.strptime(normalized, fmt)
            return int(parsed.timestamp())
        except ValueError:
            continue
    return 0


async def _safe_content(page: Any) -> str:
    try:
        return await page.content()
    except Exception:
        return ""


async def _scroll_and_fix_lazy_images(page: Any) -> None:
    try:
        await page.evaluate(
            """async () => {
                const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                const height = Math.max(document.body.scrollHeight, 1);
                for (let y = 0; y <= height; y += 500) {
                    window.scrollTo(0, y);
                    await sleep(120);
                }
                document.querySelectorAll('img').forEach((img) => {
                    const dataSrc = img.getAttribute('data-src');
                    const src = img.getAttribute('src');
                    if (dataSrc && (!src || src.startsWith('data:'))) {
                        img.setAttribute('src', dataSrc);
                    }
                });
                window.scrollTo(0, 0);
            }"""
        )
    except Exception:
        pass


def _cookies_for_playwright(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for cookie in cookies:
        name = str(cookie.get("name", ""))
        value = str(cookie.get("value", ""))
        if not name:
            continue
        item = {
            "name": name,
            "value": value,
            "domain": str(cookie.get("domain") or "mp.weixin.qq.com"),
            "path": str(cookie.get("path") or "/"),
        }
        expires = cookie.get("expires", cookie.get("expiry"))
        try:
            if expires is not None and float(expires) > 0:
                item["expires"] = int(float(expires))
        except (TypeError, ValueError):
            pass
        result.append(item)
    return result

