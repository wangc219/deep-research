from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path
from typing import Any

from .accounts import DEFAULT_ACCOUNTS, accounts_by_name
from .article_fetcher import ArticleFetcher
from .auth import login_with_qr
from .mp_api import WechatApiError, WechatMpApi, fakeid_to_mp_id
from .session_store import (
    DEFAULT_QR_PATH,
    DEFAULT_SESSION_PATH,
    load_session,
    load_werss_session,
    redacted_session_summary,
    save_session,
)
from .storage import CollectionStorage, DEFAULT_OUTPUT_DIR


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except (WechatApiError, FileNotFoundError, KeyError, TimeoutError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local WeChat MP collector")
    parser.add_argument("--session", default=str(DEFAULT_SESSION_PATH), help="session JSON path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth = subparsers.add_parser("auth", help="scan QR code and save a local session")
    auth.add_argument("--qr-file", default=str(DEFAULT_QR_PATH), help="QR screenshot path")
    auth.add_argument("--timeout", type=int, default=300, help="login timeout seconds")
    auth.add_argument("--browser", choices=["webkit", "chromium", "firefox"], default="webkit")
    auth.add_argument("--headless", action="store_true", help="do not open a visible browser window")

    import_werss = subparsers.add_parser("import-werss", help="import an existing we-mp-rss wx.lic session")
    import_werss.add_argument("wx_lic", help="path to we-mp-rss-main/data/wx.lic")

    search = subparsers.add_parser("search", help="search a WeChat MP account")
    search.add_argument("keyword")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--json", action="store_true", help="print raw JSON")

    subparsers.add_parser("list-accounts", help="list built-in account shortcuts")

    collect = subparsers.add_parser("collect", help="search account by name and collect articles")
    collect.add_argument("keyword")
    add_collect_args(collect)

    collect_by_fakeid = subparsers.add_parser("collect-by-fakeid", help="collect articles by known fakeid")
    collect_by_fakeid.add_argument("fakeid")
    collect_by_fakeid.add_argument("--name", default="", help="account display name")
    add_collect_args(collect_by_fakeid)

    collect_many = subparsers.add_parser("collect-many", help="collect built-in accounts in sequence")
    collect_many.add_argument(
        "names",
        nargs="*",
        help="optional built-in account names, aliases, or fakeids; defaults to all built-in accounts",
    )
    collect_many.add_argument("--account-delay", default="5:12", help="delay range between accounts")
    collect_many.add_argument("--stop-on-error", action="store_true", help="stop when one account fails")
    add_collect_args(collect_many)
    return parser


def add_collect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--start-page", type=int, default=0)
    parser.add_argument("--max-articles", type=int, default=0)
    parser.add_argument("--delay", default="3:8", help="list API delay range, seconds, for example 3:8")
    parser.add_argument("--content-delay", default="2:5", help="article content delay range, seconds")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--no-content", action="store_true")
    parser.add_argument("--browser", choices=["webkit", "chromium", "firefox"], default="webkit")
    parser.add_argument("--content-headless", action="store_true", default=True)
    parser.add_argument("--insecure", action="store_true", help="disable TLS certificate verification for API calls")


async def run(args: argparse.Namespace) -> int:
    session_path = Path(args.session)
    if args.command == "auth":
        print("Opening WeChat MP login page. Scan the QR code in the browser window.")
        print(f"QR screenshot will be saved to: {Path(args.qr_file)}")
        session = await login_with_qr(
            session_path=session_path,
            qr_path=Path(args.qr_file),
            timeout=args.timeout,
            browser_type=args.browser,
            headless=args.headless,
        )
        print(f"Session saved: {session_path}")
        print(json.dumps(redacted_session_summary(session), ensure_ascii=False, indent=2))
        return 0

    if args.command == "import-werss":
        session = load_werss_session(args.wx_lic)
        save_session(session, session_path)
        print(f"Session imported: {session_path}")
        print(json.dumps(redacted_session_summary(session), ensure_ascii=False, indent=2))
        return 0

    session = load_session(session_path)
    api = WechatMpApi(session, verify_tls=not getattr(args, "insecure", False))

    if args.command == "list-accounts":
        print_builtin_accounts()
        return 0

    if args.command == "search":
        payload = api.search_biz(args.keyword, limit=args.limit)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_search_results(payload)
        return 0

    if args.command == "collect":
        payload = api.search_biz(args.keyword, limit=10)
        account = choose_account(payload.get("list") or [], args.keyword)
        if not account:
            raise RuntimeError(f"account not found for keyword: {args.keyword}")
        return await collect_account(args, api, session, account)

    if args.command == "collect-by-fakeid":
        account = {
            "fakeid": args.fakeid,
            "nickname": args.name or args.fakeid,
            "alias": "",
            "mp_id": fakeid_to_mp_id(args.fakeid),
        }
        return await collect_account(args, api, session, account)

    if args.command == "collect-many":
        accounts = accounts_by_name(args.names)
        failures: list[tuple[str, str]] = []
        for index, account in enumerate(accounts, start=1):
            nickname = str(account.get("nickname") or account.get("fakeid"))
            print(f"\n=== [{index}/{len(accounts)}] {nickname} ===")
            try:
                await collect_account(args, api, session, account)
            except Exception as exc:
                failures.append((nickname, str(exc)))
                print(f"ERROR collecting {nickname}: {exc}", file=sys.stderr)
                if args.stop_on_error:
                    raise
            if index < len(accounts):
                await asyncio.sleep(random.uniform(*parse_delay(args.account_delay)))
        if failures:
            print("\nFailed accounts:")
            for name, error in failures:
                print(f"- {name}: {error}")
            return 1
        return 0

    raise RuntimeError(f"unknown command: {args.command}")


async def collect_account(
    args: argparse.Namespace,
    api: WechatMpApi,
    session: dict[str, Any],
    account: dict[str, Any],
) -> int:
    fakeid = str(account.get("fakeid") or "")
    if not fakeid:
        raise RuntimeError("selected account has no fakeid")

    account = dict(account)
    account.setdefault("mp_id", fakeid_to_mp_id(fakeid))
    print(f"Collecting account: {account.get('nickname') or account.get('name') or fakeid}")
    print(f"fakeid: {fakeid}")

    articles = api.list_articles(
        fakeid,
        pages=max(args.pages, 0),
        start_page=max(args.start_page, 0),
        delay_range=parse_delay(args.delay),
    )
    if args.max_articles and args.max_articles > 0:
        articles = articles[: args.max_articles]
    print(f"Article list fetched: {len(articles)}")

    if not args.no_content and articles:
        delay_range = parse_delay(args.content_delay)
        async with ArticleFetcher(session, browser_type=args.browser, headless=args.content_headless) as fetcher:
            for index, article in enumerate(articles, start=1):
                title = article.get("title") or article.get("url") or article.get("aid")
                print(f"[{index}/{len(articles)}] fetching content: {title}")
                detail = await fetcher.fetch(str(article.get("url") or ""))
                article.update(detail)
                if index < len(articles):
                    await asyncio.sleep(random.uniform(*delay_range))

    paths = CollectionStorage(args.output).write_collection(account=account, articles=articles)
    print(f"Saved to: {paths['account_dir']}")
    print(f"JSONL: {paths['articles_jsonl']}")
    print(f"HTML: {paths['html_dir']}")
    print(f"Markdown: {paths['markdown_dir']}")
    return 0


def print_search_results(payload: dict[str, Any]) -> None:
    items = payload.get("list") or []
    print(f"Found: {len(items)}")
    for index, item in enumerate(items, start=1):
        nickname = item.get("nickname", "")
        alias = item.get("alias", "")
        fakeid = item.get("fakeid", "")
        signature = item.get("signature", "")
        print(f"{index}. {nickname} | alias={alias} | fakeid={fakeid}")
        if signature:
            print(f"   {signature}")


def print_builtin_accounts() -> None:
    print(f"Built-in accounts: {len(DEFAULT_ACCOUNTS)}")
    for index, account in enumerate(DEFAULT_ACCOUNTS, start=1):
        print(
            f"{index}. {account.get('nickname', '')} "
            f"| alias={account.get('alias', '')} "
            f"| fakeid={account.get('fakeid', '')}"
        )
        signature = account.get("signature", "")
        if signature:
            print(f"   {signature}")


def choose_account(items: list[dict[str, Any]], keyword: str) -> dict[str, Any] | None:
    keyword = keyword.strip()
    for item in items:
        if item.get("nickname") == keyword or item.get("alias") == keyword:
            return item
    return items[0] if items else None


def parse_delay(value: str) -> tuple[float, float]:
    if ":" not in value:
        seconds = max(float(value), 0.0)
        return (seconds, seconds)
    low_text, high_text = value.split(":", 1)
    low = max(float(low_text), 0.0)
    high = max(float(high_text), low)
    return (low, high)
