"""Download public PDF files from the KTFY journal portal.

This script only handles public archive pages and public PDF endpoints. It does
not decide whether downloaded documents become facts, source claims, or graph
evidence.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin

from journal_download_common import (
    issue_directory_name,
    load_completed_paper_ids,
    normalize_issue,
    request_bytes,
    request_text,
    safe_filename,
    skip_reason,
    write_manifest,
)


BASE_URL = "https://www.spacejournal.cn"
DEFAULT_ARCHIVE_URL = "https://www.spacejournal.cn/ktfy/archive_list"
CHECK_PDF_URL_TMPL = "https://www.spacejournal.cn/ktfy/article/checkArticlePdf?id={article_id}"
EXPORT_PDF_URL_TMPL = "https://www.spacejournal.cn/ktfy/article/exportPdf?id={article_id}"
DEFAULT_OUTPUT_DIR = "data/raw/ktfy/papers"
DEFAULT_MANIFEST = "data/raw/ktfy/manifest.jsonl"


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


def request_form_json(
    url: str,
    form: dict[str, str],
    referer: str,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    request_headers = {
        "User-Agent": "Mozilla/5.0 collection-probe",
        "Referer": referer,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
    }
    if headers:
        request_headers.update(headers)
    data, _ = request_bytes(
        url,
        headers=request_headers,
        method="POST",
        data=urlencode(form).encode("utf-8"),
    )
    return json.loads(data.decode("utf-8"))


def parse_issues(html: str) -> list[Issue]:
    anchor_pattern = re.compile(
        r"<a\b[^>]*href=(?P<quote>['\"])(?P<href>[^'\"]+)(?P=quote)[^>]*>",
        re.I,
    )
    href_pattern = re.compile(r"/ktfy/(?:cn/)?article/(\d{4})/(\d{1,2})(?:[/?#]|$)", re.I)
    issues_by_key: dict[tuple[str, str], Issue] = {}

    for anchor in anchor_pattern.finditer(html):
        href = html_lib.unescape(anchor.group("href")).strip()
        match = href_pattern.search(href)
        if not match:
            continue
        year = match.group(1)
        issue = normalize_issue(match.group(2))
        url = urljoin(BASE_URL, href)
        key = (year, issue)
        existing = issues_by_key.get(key)
        if existing is None or "/cn/article/" in url:
            issues_by_key[key] = Issue(year=year, issue=issue, url=url)

    return list(issues_by_key.values())


def parse_issue_urls(html: str) -> list[str]:
    return [issue.url for issue in parse_issues(html)]


def parse_issues_from_catalog_map(payload: dict[str, object]) -> list[Issue]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    archive_list = data.get("archive_list")
    if not isinstance(archive_list, dict):
        return []

    issues: list[Issue] = []
    seen: set[tuple[str, str]] = set()
    for year_key, records in archive_list.items():
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            year = str(record.get("year") or year_key).strip()
            issue = normalize_issue(str(record.get("issue") or ""))
            if not year or not issue:
                continue
            key = (year, issue)
            if key in seen:
                continue
            seen.add(key)
            issue_num = str(int(issue)) if issue.isdigit() else issue
            issues.append(
                Issue(
                    year=year,
                    issue=issue,
                    url=f"https://www.spacejournal.cn/ktfy/cn/article/{year}/{issue_num}",
                )
            )
    return issues


def select_issue_from_list(issues: Iterable[Issue], year: str, issue: str) -> str:
    target_year = year.strip()
    target_issue = normalize_issue(issue)
    for candidate in issues:
        if candidate.year == target_year and candidate.issue == target_issue:
            return candidate.url
    raise ValueError(f"Issue not found on archive page: year={target_year}, issue={target_issue}")


def select_issue_url(html: str, year: str, issue: str) -> str:
    return select_issue_from_list(parse_issues(html), year=year, issue=issue)


def resolve_issue_url(archive_url: str, year: str, issue: str) -> str:
    html = request_text(archive_url, headers={"User-Agent": "Mozilla/5.0 collection-probe"})
    try:
        return select_issue_url(html, year=year, issue=issue)
    except ValueError:
        catalog_map_url = urljoin(archive_url, "/ktfy/data/catalog/catalogMap")
        payload = request_form_json(catalog_map_url, {"type": "1"}, referer=archive_url)
        return select_issue_from_list(parse_issues_from_catalog_map(payload), year=year, issue=issue)


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _image_alt(fragment: str) -> str:
    match = re.search(r"<img\b[^>]*\balt=(?P<quote>['\"])(?P<alt>.*?)(?P=quote)", fragment, re.I | re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html_lib.unescape(match.group("alt"))).strip()


def _is_template_value(value: str) -> bool:
    return "{{" in value or "}}" in value


def parse_papers(html: str, source_page: str) -> list[Paper]:
    anchor_pattern = re.compile(
        r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        re.I | re.S,
    )
    href_pattern = re.compile(
        r"href=(?P<quote>['\"])(?P<href>[^'\"]*/ktfy/article/id/([^?'\"]+)[^'\"]*)(?P=quote)",
        re.I | re.S,
    )
    download_pattern = re.compile(r"downloadpdf\(\s*['\"]([^'\"]+)['\"]\s*\)", re.I)

    title_by_id: dict[str, str] = {}
    page_by_id: dict[str, str] = {}
    for anchor in anchor_pattern.finditer(html):
        attrs = anchor.group("attrs")
        href_match = href_pattern.search(attrs)
        if not href_match:
            continue
        article_id = href_match.group(3).strip()
        if _is_template_value(article_id):
            continue
        body = anchor.group("body")
        text = _strip_tags(body)
        if text in {"", "施引文献"}:
            text = _image_alt(body)
        if _is_template_value(text):
            continue
        if text and article_id not in title_by_id:
            title_by_id[article_id] = text
        page_by_id.setdefault(article_id, urljoin(BASE_URL, href_match.group("href").strip()))

    papers: list[Paper] = []
    seen: set[str] = set()
    for article_id in download_pattern.findall(html):
        article_id = article_id.strip()
        if _is_template_value(article_id):
            continue
        if article_id in seen:
            continue
        seen.add(article_id)
        papers.append(
            Paper(
                article_id=article_id,
                title=title_by_id.get(article_id, article_id),
                article_page=page_by_id.get(article_id, urljoin(BASE_URL, f"/ktfy/article/id/{article_id}")),
                source_page=source_page,
            )
        )
    return papers


def discover_papers(seed_urls: Iterable[str], max_issues: int) -> list[Paper]:
    queue = list(seed_urls)
    visited: set[str] = set()
    papers: list[Paper] = []
    issue_count = 0

    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        html = request_text(url, headers={"User-Agent": "Mozilla/5.0 collection-probe"})
        papers.extend(parse_papers(html, source_page=url))

        if issue_count < max_issues:
            for issue_url in parse_issue_urls(html):
                if issue_url not in visited and issue_url not in queue:
                    queue.append(issue_url)
                    issue_count += 1
                    if issue_count >= max_issues:
                        break

    unique: dict[str, Paper] = {}
    for paper in papers:
        unique.setdefault(paper.article_id, paper)
    return list(unique.values())


def check_pdf_access(paper: Paper) -> dict[str, object]:
    url = CHECK_PDF_URL_TMPL.format(article_id=quote(paper.article_id, safe=""))
    data, _ = request_bytes(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 collection-probe",
            "Referer": paper.source_page or DEFAULT_ARCHIVE_URL,
        },
        method="POST",
    )
    payload = json.loads(data.decode("utf-8"))
    if payload.get("access") != "true":
        raise ValueError(f"PDF access denied for {paper.title}: {payload.get('access')}")
    if payload.get("result") != "true":
        raise ValueError(f"PDF not available for {paper.title}")
    return payload


def output_path_for_paper(paper: Paper, output_dir: Path) -> Path:
    return output_dir / safe_filename(paper.title)


def download_pdf(paper: Paper, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    access = check_pdf_access(paper)
    url = EXPORT_PDF_URL_TMPL.format(article_id=quote(paper.article_id, safe=""))
    data, response_headers = request_bytes(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 collection-probe",
            "Referer": paper.source_page or DEFAULT_ARCHIVE_URL,
        },
    )
    if not data.startswith(b"%PDF"):
        raise ValueError(f"Downloaded content is not a PDF: {paper.title}")

    path = output_path_for_paper(paper, output_dir)
    path.write_bytes(data)
    content_type = ""
    content_disposition = ""
    for key, value in response_headers.items():
        if key.lower() == "content-type":
            content_type = value
        elif key.lower() == "content-disposition":
            content_disposition = value
    return {
        "paper": asdict(paper),
        "status": "downloaded",
        "check_pdf": access,
        "download_url": url,
        "file": str(path),
        "size": path.stat().st_size,
        "content_type": content_type,
        "content_disposition": content_disposition,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download public PDFs from KTFY journal portal.")
    parser.add_argument("--archive-url", default=DEFAULT_ARCHIVE_URL)
    parser.add_argument("--issue-url", action="append", default=[])
    parser.add_argument("--year")
    parser.add_argument("--issue")
    parser.add_argument("--article-id")
    parser.add_argument("--title")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--max-issues", type=int, default=0)
    parser.add_argument("--max-papers", type=int, default=1)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if bool(args.year) != bool(args.issue):
        parser.error("--year and --issue must be used together")
    if args.article_id and (args.year or args.issue):
        parser.error("--year/--issue cannot be used with --article-id")

    if args.year and args.issue:
        issue_dir = issue_directory_name(args.year, args.issue)
        if args.output_dir == DEFAULT_OUTPUT_DIR:
            args.output_dir = f"data/raw/ktfy/{issue_dir}/papers"
        if args.manifest == DEFAULT_MANIFEST:
            args.manifest = f"data/raw/ktfy/{issue_dir}/manifest.jsonl"

    if args.article_id:
        if not args.title:
            parser.error("--title is required with --article-id")
        papers = [
            Paper(
                article_id=args.article_id,
                title=args.title,
                article_page=urljoin(BASE_URL, f"/ktfy/article/id/{args.article_id}"),
                source_page=args.archive_url,
            )
        ]
    elif args.year and args.issue:
        issue_url = resolve_issue_url(args.archive_url, year=args.year, issue=args.issue)
        papers = discover_papers(seed_urls=[issue_url], max_issues=0)
    else:
        seed_urls = [args.archive_url, *args.issue_url]
        papers = discover_papers(seed_urls=seed_urls, max_issues=args.max_issues)

    if args.max_papers >= 0:
        papers = papers[: args.max_papers]

    if args.dry_run:
        print(json.dumps([asdict(paper) for paper in papers], ensure_ascii=False, indent=2))
        return 0

    output_dir = Path(args.output_dir)
    manifest_path = Path(args.manifest)
    completed_ids = load_completed_paper_ids(manifest_path)
    for index, paper in enumerate(papers, start=1):
        path = output_path_for_paper(paper, output_dir)
        reason = skip_reason(paper.article_id, path, completed_ids)
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

        record = download_pdf(paper, output_dir=output_dir)
        record["downloaded_at"] = int(time.time())
        write_manifest(record, manifest_path)
        completed_ids.add(paper.article_id)
        print(json.dumps(record, ensure_ascii=False))
        if index < len(papers) and args.sleep > 0:
            time.sleep(args.sleep)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        print(f"download_ktfy.py: {exc}", file=sys.stderr)
        raise SystemExit(1)
