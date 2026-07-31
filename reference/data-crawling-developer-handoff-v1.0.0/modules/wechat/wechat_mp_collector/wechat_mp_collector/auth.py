from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path
from typing import Any

from .session_store import DEFAULT_QR_PATH, DEFAULT_SESSION_PATH, build_session, save_session


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def login_with_qr(
    *,
    session_path: Path | str = DEFAULT_SESSION_PATH,
    qr_path: Path | str = DEFAULT_QR_PATH,
    timeout: int = 300,
    browser_type: str = "webkit",
    headless: bool = False,
) -> dict[str, Any]:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright

    session_target = Path(session_path)
    qr_target = Path(qr_path)
    qr_target.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        launcher = getattr(playwright, browser_type)
        browser = await launcher.launch(headless=headless)
        context = await browser.new_context(
            user_agent=DESKTOP_UA,
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = await context.new_page()
        try:
            await page.goto("https://mp.weixin.qq.com/", wait_until="domcontentloaded", timeout=60_000)
            await _save_qr_image(page, qr_target)
            token = await _wait_for_login_token(page, context, timeout=timeout)
            cookies = await context.cookies()
            session = build_session(
                token=token,
                cookies=cookies,
                user_agent=DESKTOP_UA,
                extra={"auth_url": page.url, "browser_type": browser_type},
            )
            save_session(session, session_target)
            return session
        except PlaywrightTimeoutError as exc:
            raise TimeoutError(f"QR login timed out after {timeout} seconds") from exc
        finally:
            await context.close()
            await browser.close()


async def _save_qr_image(page: Any, qr_path: Path) -> None:
    selectors = [
        "img[src*='scanloginqrcode']",
        ".login__type__container__scan__qrcode img",
        "img[src*='qrcode']",
        ".login__type__container__scan__qrcode",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=10_000)
            await page.wait_for_function(
                """(selector) => {
                    const element = document.querySelector(selector);
                    if (!element) return false;
                    if (element.tagName && element.tagName.toLowerCase() === 'img') {
                        return element.complete && element.naturalWidth > 0 && element.naturalHeight > 0;
                    }
                    const image = element.querySelector && element.querySelector("img");
                    return !image || (image.complete && image.naturalWidth > 0 && image.naturalHeight > 0);
                }""",
                selector,
                timeout=10_000,
            )
            await locator.screenshot(path=str(qr_path))
            return
        except Exception:
            continue
    await page.screenshot(path=str(qr_path), full_page=True)


async def _wait_for_login_token(page: Any, context: Any, *, timeout: int) -> str:
    deadline = time.time() + timeout
    last_url = ""
    while time.time() < deadline:
        token = await extract_token(page, context)
        current_url = page.url
        if token and ("mp.weixin.qq.com" in current_url):
            return token
        if current_url != last_url:
            last_url = current_url
        await page.wait_for_timeout(1000)
    raise TimeoutError(f"QR login timed out after {timeout} seconds")


async def extract_token(page: Any, context: Any) -> str:
    for source in [page.url, await _safe_content(page)]:
        match = re.search(r"[?&]token=([0-9A-Za-z_-]+)", source or "")
        if match:
            return match.group(1)

    for storage_name in ["localStorage", "sessionStorage"]:
        try:
            token = await page.evaluate(f"() => {storage_name}.getItem('token')")
            if token:
                return str(token)
        except Exception:
            pass

    try:
        for cookie in await context.cookies():
            if "token" in str(cookie.get("name", "")).lower():
                value = str(cookie.get("value", ""))
                if value:
                    return value
    except Exception:
        pass
    return ""


async def _safe_content(page: Any) -> str:
    try:
        return await page.content()
    except Exception:
        return ""
