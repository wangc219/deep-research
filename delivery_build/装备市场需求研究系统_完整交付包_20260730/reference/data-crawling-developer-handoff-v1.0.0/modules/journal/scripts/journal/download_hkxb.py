"""Download public PDF files from the 航空学报 archive."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from http.client import IncompleteRead, InvalidURL, RemoteDisconnected
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin

from journal_download_common import (
    DEFAULT_USER_AGENT,
    call_with_retries,
    issue_directory_name,
    load_completed_paper_ids,
    load_cookie_header,
    normalize_issue,
    request_bytes,
    request_form_text,
    request_text,
    response_header,
    safe_header_value,
    safe_filename,
    skip_reason,
    write_manifest,
)


BASE_URL = "https://hkxb.buaa.edu.cn"
DEFAULT_ARCHIVE_URL = "https://hkxb.buaa.edu.cn/CN/article/showTenYearOldVolumn.do"
YEAR_URL_TMPL = "https://hkxb.buaa.edu.cn/CN/article/showTenYearVolumnDetail.do?nian={year}"
PDF_INFO_URL = "https://hkxb.buaa.edu.cn/CN/article/showArticleFile.do"
DEFAULT_OUTPUT_DIR = "data/raw/hkxb/papers"
DEFAULT_MANIFEST = "data/raw/hkxb/manifest.jsonl"
DOWNLOAD_ATTEMPTS = 3


@dataclass
class Issue:
    year: str
    issue: str
    url: str


@dataclass
class Paper:
    article_id: str
    title: str
    article_page: str
    source_page: str


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html_lib.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_issues(html: str) -> list[Issue]:
    anchor_pattern = re.compile(
        r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        re.I | re.S,
    )
    href_pattern = re.compile(
        r"href=(?P<quote>['\"])(?P<href>[^'\"]*volumn/volumn_\d+\.shtml)(?P=quote)",
        re.I,
    )

    issues: list[Issue] = []
    seen: set[tuple[str, str]] = set()
    for anchor in anchor_pattern.finditer(html):
        attrs = anchor.group("attrs")
        href_match = href_pattern.search(attrs)
        if not href_match:
            continue
        text = _strip_tags(anchor.group("body"))
        issue_match = re.search(r"(?P<year>\d{4}).*?No\.(?P<issue>[A-Za-z0-9]+)", text, re.I)
        if not issue_match:
            continue
        year = issue_match.group("year")
        issue = normalize_issue(issue_match.group("issue"))
        key = (year, issue)
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            Issue(
                year=year,
                issue=issue,
                url=urljoin(f"{BASE_URL}/CN/article/", href_match.group("href")),
            )
        )
    return issues


def select_issue_from_list(issues: Iterable[Issue], year: str, issue: str) -> str:
    target_year = year.strip()
    target_issue = normalize_issue(issue)
    for candidate in issues:
        if candidate.year == target_year and candidate.issue == target_issue:
            return candidate.url
    raise ValueError(f"Issue not found on HKXB archive page: year={target_year}, issue={target_issue}")


def select_issue_url(html: str, year: str, issue: str) -> str:
    return select_issue_from_list(parse_issues(html), year=year, issue=issue)


def resolve_issue_url(year: str, issue: str) -> str:
    year_url = YEAR_URL_TMPL.format(year=quote(year.strip(), safe=""))
    html = request_text(year_url, headers={"User-Agent": DEFAULT_USER_AGENT})
    return select_issue_url(html, year=year, issue=issue)


def _last_article_link(fragment: str) -> tuple[str, str]:
    anchor_pattern = re.compile(
        r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        re.I | re.S,
    )
    href_pattern = re.compile(r"href=(?P<quote>['\"])(?P<href>[^'\"]+)(?P=quote)", re.I)
    ignored_text = {
        "摘要",
        "数据和表",
        "参考文献",
        "相关文章",
        "计量指标",
        "收藏",
        "下载",
        "浏览量",
    }

    candidates: list[tuple[str, str]] = []
    for anchor in anchor_pattern.finditer(fragment):
        href_match = href_pattern.search(anchor.group("attrs"))
        if not href_match:
            continue
        href = html_lib.unescape(href_match.group("href")).strip()
        text = _strip_tags(anchor.group("body"))
        if not text or text in ignored_text or "电子期刊" in text:
            continue
        if href.startswith("#") or "doi.org" in href:
            continue
        if "/CN/10." not in href and "/CN/abstract/abstract" not in href:
            continue
        candidates.append((text, urljoin(BASE_URL, href)))

    return candidates[-1] if candidates else ("", "")


def parse_papers(html: str, source_page: str) -> list[Paper]:
    pdf_pattern = re.compile(
        r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        re.I | re.S,
    )
    onclick_pattern = re.compile(
        r"lsdy1\(\s*['\"]PDF['\"]\s*,\s*['\"](?P<article_id>\d+)['\"]",
        re.I,
    )

    papers: list[Paper] = []
    seen: set[str] = set()
    previous_end = 0
    for anchor in pdf_pattern.finditer(html):
        onclick = onclick_pattern.search(anchor.group("attrs"))
        if not onclick:
            continue
        article_id = onclick.group("article_id")
        if article_id in seen:
            previous_end = anchor.end()
            continue
        title, article_page = _last_article_link(html[previous_end : anchor.start()])
        previous_end = anchor.end()
        if not title:
            continue
        seen.add(article_id)
        papers.append(
            Paper(
                article_id=article_id,
                title=title,
                article_page=article_page,
                source_page=source_page,
            )
        )
    return papers


def discover_papers(issue_urls: Iterable[str]) -> list[Paper]:
    papers: list[Paper] = []
    for issue_url in issue_urls:
        html = request_text(issue_url, headers={"User-Agent": DEFAULT_USER_AGENT})
        papers.extend(parse_papers(html, source_page=issue_url))

    unique: dict[str, Paper] = {}
    for paper in papers:
        unique.setdefault(paper.article_id, paper)
    return list(unique.values())


def parse_pdf_payload(payload: str) -> str:
    payload = payload.strip()
    if payload.startswith("[json]"):
        payload = payload[len("[json]") :]
    data = json.loads(payload)
    if data.get("status") != 1:
        raise ValueError(f"HKXB PDF endpoint returned status={data.get('status')}")
    pdf_url = re.sub(r"\s+", "", str(data.get("pdfUrl") or "").strip())
    if not pdf_url:
        raise ValueError("HKXB PDF endpoint did not return pdfUrl")
    return pdf_url


def json_line(record: object) -> str:
    return json.dumps(record, ensure_ascii=True)


def resolve_pdf_url(paper: Paper, cookie_header: str = "") -> str:
    headers = {"Cookie": cookie_header} if cookie_header else None
    payload = request_form_text(
        PDF_INFO_URL,
        {"attachType": "PDF", "id": paper.article_id, "json": "true"},
        referer=paper.source_page,
        headers=headers,
    )
    return parse_pdf_payload(payload)


def request_bytes_with_retries(
    url: str,
    headers: dict[str, str],
    attempts: int = DOWNLOAD_ATTEMPTS,
) -> tuple[bytes, dict[str, str]]:
    return call_with_retries(
        lambda: request_bytes(url, headers=headers),
        attempts=attempts,
        retry_exceptions=(
            URLError,
            IncompleteRead,
            RemoteDisconnected,
            TimeoutError,
        ),
    )


def output_path_for_paper(paper: Paper, output_dir: Path) -> Path:
    return output_dir / safe_filename(f"{paper.article_id}_{paper.title}")


def download_pdf(paper: Paper, output_dir: Path, cookie_header: str = "") -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_url = resolve_pdf_url(paper, cookie_header=cookie_header)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": paper.source_page,
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    data, response_headers = request_bytes_with_retries(pdf_url, headers=headers)
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
        "download_url": pdf_url,
        "file": str(path),
        "size": path.stat().st_size,
        "content_type": safe_header_value(response_header(response_headers, "Content-Type")),
        "content_disposition": safe_header_value(response_header(response_headers, "Content-Disposition")),
    }


def _limit_papers(papers: list[Paper], max_papers: int) -> list[Paper]:
    if max_papers >= 0:
        return papers[:max_papers]
    return papers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download public PDFs from 航空学报.")
    parser.add_argument("--archive-url", default=DEFAULT_ARCHIVE_URL)
    parser.add_argument("--issue-url", action="append", default=[])
    parser.add_argument("--year")
    parser.add_argument("--issue")
    parser.add_argument("--article-id")
    parser.add_argument("--title")
    parser.add_argument("--article-page")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--max-papers", type=int, default=1)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--cookie")
    parser.add_argument("--cookie-file")
    args = parser.parse_args(argv)

    if bool(args.year) != bool(args.issue):
        parser.error("--year and --issue must be used together")
    if args.article_id and (args.year or args.issue or args.issue_url):
        parser.error("--year/--issue/--issue-url cannot be used with --article-id")

    if args.year and args.issue:
        issue_dir = issue_directory_name(args.year, args.issue)
        if args.output_dir == DEFAULT_OUTPUT_DIR:
            args.output_dir = f"data/raw/hkxb/{issue_dir}/papers"
        if args.manifest == DEFAULT_MANIFEST:
            args.manifest = f"data/raw/hkxb/{issue_dir}/manifest.jsonl"

    if args.article_id:
        title = args.title or args.article_id
        article_page = args.article_page or urljoin(BASE_URL, f"/CN/abstract/abstract{args.article_id}.shtml")
        papers = [
            Paper(
                article_id=args.article_id,
                title=title,
                article_page=article_page,
                source_page=args.archive_url,
            )
        ]
    else:
        issue_urls = list(args.issue_url)
        if args.year and args.issue:
            issue_urls.insert(0, resolve_issue_url(args.year, args.issue))
        if not issue_urls:
            parser.error("--year/--issue, --issue-url, or --article-id is required")
        papers = discover_papers(issue_urls)

    papers = _limit_papers(papers, args.max_papers)
    if args.dry_run:
        print(json.dumps([asdict(paper) for paper in papers], ensure_ascii=True, indent=2))
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
            print(json_line(record))
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
            print(json_line(record))
            continue

        try:
            record = download_pdf(paper, output_dir=output_dir, cookie_header=cookie_header)
            record["downloaded_at"] = int(time.time())
            write_manifest(record, manifest_path)
            completed_ids.add(paper.article_id)
            print(json_line(record))
        except (
            HTTPError,
            URLError,
            ValueError,
            json.JSONDecodeError,
            IncompleteRead,
            InvalidURL,
            RemoteDisconnected,
            TimeoutError,
        ) as exc:
            failed = True
            record = {
                "status": "failed",
                "paper": asdict(paper),
                "error": str(exc),
                "downloaded_at": int(time.time()),
            }
            write_manifest(record, manifest_path)
            print(json_line(record), file=sys.stderr)
            if args.strict:
                return 1

        if index < len(papers) and args.sleep > 0:
            time.sleep(args.sleep)

    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        HTTPError,
        URLError,
        ValueError,
        json.JSONDecodeError,
        IncompleteRead,
        InvalidURL,
        RemoteDisconnected,
        TimeoutError,
    ) as exc:
        print(f"download_hkxb.py: {exc}", file=sys.stderr)
        raise SystemExit(1)
