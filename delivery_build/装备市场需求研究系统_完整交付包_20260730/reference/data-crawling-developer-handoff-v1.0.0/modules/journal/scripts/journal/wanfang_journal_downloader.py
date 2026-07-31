"""Shared downloader for Wanfang-hosted periodical issues."""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from journal_download_common import (
    DEFAULT_USER_AGENT,
    call_with_retries,
    issue_directory_name,
    load_completed_paper_ids,
    load_cookie_header,
    normalize_issue,
    request_bytes,
    response_header,
    safe_header_value,
    safe_filename,
    skip_reason,
    write_manifest,
)


BASE_DETAIL_URL = "https://d.wanfangdata.com.cn/periodical"
BASE_MAGAZINE_URL = "https://c.wanfangdata.com.cn/magazine"
DOWNLOAD_URL_TMPL = "https://oss.wanfangdata.com.cn/file/download/perio_{article_id}.aspx"
DOWNLOAD_ATTEMPTS = 3


@dataclass
class WanfangJournalConfig:
    journal_id: str
    journal_name: str
    output_slug: str


@dataclass
class Paper:
    article_id: str
    title: str
    detail_url: str
    download_url: str
    source_page: str


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def build_issue_url(config: WanfangJournalConfig, year: str, issue: str, page: int = 1) -> str:
    query = urlencode(
        {
            "tabId": "article",
            "publishYear": year.strip(),
            "issueNum": normalize_issue(issue),
            "page": str(page),
            "isSync": "0",
        }
    )
    return f"{BASE_MAGAZINE_URL}/{config.journal_id}?{query}"


def build_article_id(config: WanfangJournalConfig, year: str, issue: str, sequence: int) -> str:
    return f"{config.journal_id}{year.strip()}{normalize_issue(issue)}{sequence:03d}"


def build_download_url(article_id: str) -> str:
    return DOWNLOAD_URL_TMPL.format(article_id=quote(article_id, safe=""))


def build_detail_url(article_id: str) -> str:
    return f"{BASE_DETAIL_URL}/{quote(article_id, safe='')}"


def parse_transaction_title(location: str) -> str:
    encoded = parse_qs(urlparse(location).query).get("webTransactionRequest", [""])[0]
    if not encoded:
        return ""
    encoded += "=" * (-len(encoded) % 4)
    payload = json.loads(base64.urlsafe_b64decode(encoded.encode("utf-8")).decode("utf-8"))
    transaction = payload.get("transactionRequest")
    if not isinstance(transaction, dict):
        return ""
    return str(transaction.get("productTitle") or "").strip()


def request_head_no_redirect(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str]]:
    opener = build_opener(NoRedirectHandler)
    req = Request(url, headers=headers or {}, method="HEAD")
    try:
        with opener.open(req, timeout=60) as resp:
            return resp.status, dict(resp.headers.items())
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items())


def probe_wanfang_download(article_id: str, source_page: str) -> Paper | None:
    download_url = build_download_url(article_id)
    last_error: URLError | RemoteDisconnected | TimeoutError | None = None
    for _attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            status, headers = request_head_no_redirect(
                download_url,
                headers={"User-Agent": DEFAULT_USER_AGENT, "Referer": source_page},
            )
            break
        except (URLError, RemoteDisconnected, TimeoutError) as exc:
            last_error = exc
    else:
        if last_error is not None:
            raise last_error
        raise ValueError("download probe attempts must be positive")

    if status == 404:
        return None
    if status in {301, 302, 303, 307, 308}:
        title = parse_transaction_title(response_header(headers, "Location")) or article_id
    elif status == 200:
        title = article_id
    else:
        raise ValueError(f"Unexpected Wanfang probe status for {article_id}: HTTP {status}")

    return Paper(
        article_id=article_id,
        title=title,
        detail_url=build_detail_url(article_id),
        download_url=download_url,
        source_page=source_page,
    )


def discover_issue_papers(
    config: WanfangJournalConfig,
    year: str,
    issue: str,
    max_seq: int = 200,
    stop_after_misses: int = 10,
    probe: Callable[[str, str], Paper | None] = probe_wanfang_download,
) -> list[Paper]:
    source_page = build_issue_url(config, year, issue)
    papers: list[Paper] = []
    misses = 0

    for sequence in range(1, max_seq + 1):
        article_id = build_article_id(config, year, issue, sequence)
        paper = probe(article_id, source_page)
        if paper:
            papers.append(paper)
            misses = 0
            continue
        misses += 1
        if misses >= stop_after_misses:
            break

    unique: dict[str, Paper] = {}
    for paper in papers:
        unique.setdefault(paper.article_id, paper)
    return list(unique.values())


def parse_issue_url(url: str) -> tuple[str, str]:
    query = parse_qs(urlparse(url).query)
    year = query.get("publishYear", [""])[0]
    issue = query.get("issueNum", [""])[0]
    if not year or not issue:
        raise ValueError(f"Cannot parse publishYear/issueNum from issue URL: {url}")
    return year, issue


def output_path_for_paper(paper: Paper, output_dir: Path) -> Path:
    return output_dir / safe_filename(f"{paper.article_id}_{paper.title}")


def extract_new_fulltext_url(download_info_html: bytes, base_url: str) -> str:
    text = ""
    for encoding in ("utf-8", "gb18030"):
        try:
            text = download_info_html.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = download_info_html.decode("utf-8", errors="replace")

    match = re.search(r"""(?:src|href)=["']([^"']*NewFulltext[^"']+)["']""", text, re.I)
    if not match:
        return ""
    return urljoin(base_url, html.unescape(match.group(1)))


def request_bytes_with_retries(
    url: str,
    headers: dict[str, str],
    attempts: int = DOWNLOAD_ATTEMPTS,
) -> tuple[bytes, dict[str, str]]:
    return call_with_retries(
        lambda: request_bytes(url, headers=headers),
        attempts=attempts,
        retry_exceptions=(IncompleteRead, RemoteDisconnected),
    )


def download_pdf(paper: Paper, output_dir: Path, cookie_header: str = "") -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": paper.source_page,
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    data, response_headers = request_bytes_with_retries(paper.download_url, headers=headers)
    download_flow = "direct"
    if not data.startswith(b"%PDF"):
        content_type = response_header(response_headers, "Content-Type")
        if "text/html" in content_type.lower():
            new_fulltext_url = extract_new_fulltext_url(data, paper.download_url)
            if new_fulltext_url:
                chained_headers = dict(headers)
                chained_headers["Referer"] = paper.download_url
                data, response_headers = request_bytes_with_retries(new_fulltext_url, headers=chained_headers)
                download_flow = "new_fulltext"

    if not data.startswith(b"%PDF"):
        content_type = response_header(response_headers, "Content-Type")
        raise ValueError(
            f"Downloaded content is not a PDF for {paper.article_id}; "
            f"content-type={content_type or 'unknown'}"
        )

    path = output_path_for_paper(paper, output_dir)
    path.write_bytes(data)
    return {
        "status": "downloaded",
        "paper": asdict(paper),
        "download_url": paper.download_url,
        "download_flow": download_flow,
        "file": str(path),
        "size": path.stat().st_size,
        "content_type": safe_header_value(response_header(response_headers, "Content-Type")),
        "content_disposition": safe_header_value(response_header(response_headers, "Content-Disposition")),
    }


def _limit_papers(papers: list[Paper], max_papers: int) -> list[Paper]:
    if max_papers >= 0:
        return papers[:max_papers]
    return papers


def _default_output_dir(config: WanfangJournalConfig) -> str:
    return f"data/raw/{config.output_slug}/papers"


def _default_manifest(config: WanfangJournalConfig) -> str:
    return f"data/raw/{config.output_slug}/manifest.jsonl"


def collect_papers_from_args(config: WanfangJournalConfig, args: argparse.Namespace) -> list[Paper]:
    if args.article_id:
        title = args.title or args.article_id
        return [
            Paper(
                article_id=args.article_id,
                title=title,
                detail_url=build_detail_url(args.article_id),
                download_url=build_download_url(args.article_id),
                source_page=args.issue_url[0] if args.issue_url else f"{BASE_MAGAZINE_URL}/{config.journal_id}",
            )
        ]

    targets: list[tuple[str, str]] = []
    if args.year and args.issue:
        targets.append((args.year, args.issue))
    for issue_url in args.issue_url:
        targets.append(parse_issue_url(issue_url))
    if not targets:
        raise ValueError("--year/--issue or --issue-url is required unless --article-id is used")

    papers: list[Paper] = []
    for year, issue in targets:
        papers.extend(
            discover_issue_papers(
                config=config,
                year=year,
                issue=issue,
                max_seq=args.max_seq,
                stop_after_misses=args.stop_after_misses,
            )
        )

    unique: dict[str, Paper] = {}
    for paper in papers:
        unique.setdefault(paper.article_id, paper)
    return list(unique.values())


def main_for_config(config: WanfangJournalConfig, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Download public PDFs from {config.journal_name}.")
    parser.add_argument("--issue-url", action="append", default=[])
    parser.add_argument("--year")
    parser.add_argument("--issue")
    parser.add_argument("--article-id")
    parser.add_argument("--title")
    parser.add_argument("--output-dir", default=_default_output_dir(config))
    parser.add_argument("--manifest", default=_default_manifest(config))
    parser.add_argument("--max-papers", type=int, default=1)
    parser.add_argument("--max-seq", type=int, default=200)
    parser.add_argument("--stop-after-misses", type=int, default=10)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--cookie")
    parser.add_argument("--cookie-file")
    args = parser.parse_args(argv)

    if bool(args.year) != bool(args.issue):
        parser.error("--year and --issue must be used together")
    if args.article_id and (args.year or args.issue):
        parser.error("--year/--issue cannot be used with --article-id")
    if args.stop_after_misses < 1:
        parser.error("--stop-after-misses must be positive")

    if args.year and args.issue:
        issue_dir = issue_directory_name(args.year, args.issue)
        if args.output_dir == _default_output_dir(config):
            args.output_dir = f"data/raw/{config.output_slug}/{issue_dir}/papers"
        if args.manifest == _default_manifest(config):
            args.manifest = f"data/raw/{config.output_slug}/{issue_dir}/manifest.jsonl"

    try:
        papers = _limit_papers(collect_papers_from_args(config, args), args.max_papers)
    except (HTTPError, URLError, ValueError, RemoteDisconnected, TimeoutError) as exc:
        print(f"wanfang_journal_downloader.py: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(json.dumps([asdict(paper) for paper in papers], ensure_ascii=False, indent=2))
        return 0

    output_dir = Path(args.output_dir)
    manifest_path = Path(args.manifest)
    completed_ids = load_completed_paper_ids(manifest_path)
    cookie_header = load_cookie_header(args.cookie, args.cookie_file)
    failed = False

    for index, paper in enumerate(papers, start=1):
        path = output_path_for_paper(paper, output_dir)
        reason = skip_reason(paper.article_id, path, completed_ids, force=args.force)
        if reason == "manifest":
            record = {"status": "skipped_manifest", "paper": asdict(paper), "file": str(path)}
            print(json.dumps(record, ensure_ascii=False))
            continue
        if reason == "file_exists":
            record = {
                "status": "skipped_existing",
                "paper": asdict(paper),
                "file": str(path),
                "size": path.stat().st_size,
                "downloaded_at": int(time.time()),
            }
            write_manifest(record, manifest_path)
            completed_ids.add(paper.article_id)
            print(json.dumps(record, ensure_ascii=False))
            continue

        try:
            record = download_pdf(paper, output_dir=output_dir, cookie_header=cookie_header)
            record["downloaded_at"] = int(time.time())
            write_manifest(record, manifest_path)
            completed_ids.add(paper.article_id)
            print(json.dumps(record, ensure_ascii=False))
        except (HTTPError, URLError, ValueError, IncompleteRead, RemoteDisconnected) as exc:
            failed = True
            record = {
                "status": "failed",
                "paper": asdict(paper),
                "download_url": paper.download_url,
                "error": str(exc),
                "downloaded_at": int(time.time()),
            }
            write_manifest(record, manifest_path)
            print(json.dumps(record, ensure_ascii=False), file=sys.stderr)
            if args.strict:
                return 1

        if index < len(papers) and args.sleep > 0:
            time.sleep(args.sleep)

    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Wanfang periodical PDFs.")
    parser.add_argument("--journal-id", required=True)
    parser.add_argument("--journal-name", required=True)
    parser.add_argument("--output-slug")
    known, rest = parser.parse_known_args(argv)
    config = WanfangJournalConfig(
        journal_id=known.journal_id,
        journal_name=known.journal_name,
        output_slug=known.output_slug or known.journal_id,
    )
    return main_for_config(config, rest)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, ValueError, json.JSONDecodeError, RemoteDisconnected) as exc:
        print(f"wanfang_journal_downloader.py: {exc}", file=sys.stderr)
        raise SystemExit(1)
