"""Download public PDF files from the ZSDD journal portal.

This script is a first-pass local orchestration utility for validating the
collection flow. It does not decide whether a downloaded document becomes a
fact, source claim, or evidence item. That governance belongs to later pipeline
stages.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

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


DEFAULT_PORTAL_URL = "https://zsdd.cbpt.cnki.net/portal"
DOWNLOAD_URL_TMPL = (
    "https://zsdd.cbpt.cnki.net/portal/journal/portal/client/"
    "updateDownLoadNumber/{content_id}/{download_type}"
)
ISSUE_URL = "https://zsdd.cbpt.cnki.net/portal/journal/portal/client/guokan_list"
DEFAULT_OUTPUT_DIR = "data/raw/zsdd/papers"
DEFAULT_MANIFEST = "data/raw/zsdd/manifest.jsonl"


@dataclass
class Paper:
    content_id: str
    download_type: str
    web_id: str
    title: str
    source_page: str


@dataclass
class Issue:
    year: str
    issue: str
    year_id: str
    issue_id: str
    url: str


def parse_papers(html: str, source_page: str) -> list[Paper]:
    pattern = re.compile(
        r"downloadFull\('([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\)",
        re.I,
    )
    papers: list[Paper] = []
    seen: set[str] = set()
    for content_id, download_type, web_id, title in pattern.findall(html):
        if download_type != "1":
            continue
        key = f"{content_id}:{download_type}"
        if key in seen:
            continue
        seen.add(key)
        papers.append(
            Paper(
                content_id=content_id,
                download_type=download_type,
                web_id=web_id.strip(),
                title=title.strip(),
                source_page=source_page,
            )
        )
    return papers


def build_issue_url(year: str, issue: str, year_id: str, issue_id: str) -> str:
    query = urlencode(
        {
            "year": year,
            "issue": issue,
            "yearId": year_id,
            "issueId": issue_id,
        }
    )
    return f"{ISSUE_URL}?{query}"


def parse_issues(html: str) -> list[Issue]:
    pattern = re.compile(
        r"guokanTurnPageList\('([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\)",
        re.I,
    )
    issues: list[Issue] = []
    seen: set[str] = set()
    for year, issue, year_id, issue_id in pattern.findall(html):
        year = year.strip()
        issue = normalize_issue(issue)
        year_id = year_id.strip()
        issue_id = issue_id.strip()
        url = build_issue_url(year, issue, year_id, issue_id)
        if url not in seen:
            seen.add(url)
            issues.append(
                Issue(
                    year=year,
                    issue=issue,
                    year_id=year_id,
                    issue_id=issue_id,
                    url=url,
                )
            )
    return issues


def parse_issue_urls(html: str) -> list[str]:
    return [issue.url for issue in parse_issues(html)]


def select_issue_url(html: str, year: str, issue: str) -> str:
    target_year = year.strip()
    target_issue = normalize_issue(issue)
    for candidate in parse_issues(html):
        if candidate.year == target_year and candidate.issue == target_issue:
            return candidate.url
    raise ValueError(f"Issue not found on portal page: year={target_year}, issue={target_issue}")


def resolve_issue_url(portal_url: str, year: str, issue: str) -> str:
    html = request_text(portal_url, headers={"User-Agent": "Mozilla/5.0 collection-probe"})
    return select_issue_url(html, year=year, issue=issue)


def output_path_for_paper(paper: Paper, output_dir: Path) -> Path:
    return output_dir / safe_filename(paper.title)


def download_pdf(paper: Paper, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_path_for_paper(paper, output_dir)
    url = DOWNLOAD_URL_TMPL.format(
        content_id=quote(paper.content_id, safe=""),
        download_type=quote(paper.download_type, safe=""),
    )
    headers = {
        "User-Agent": "Mozilla/5.0 collection-probe",
        "Referer": paper.source_page or DEFAULT_PORTAL_URL,
        "web_id": paper.web_id,
    }
    data, response_headers = request_bytes(url, headers=headers)
    if not data.startswith(b"%PDF"):
        raise ValueError(f"Downloaded content is not a PDF: {paper.title}")
    path.write_bytes(data)
    content_type = ""
    for key, value in response_headers.items():
        if key.lower() == "content-type":
            content_type = value
            break
    return {
        "paper": asdict(paper),
        "status": "downloaded",
        "download_url": url,
        "file": str(path),
        "size": path.stat().st_size,
        "content_type": content_type,
    }


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
        unique.setdefault(paper.content_id, paper)
    return list(unique.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download public PDFs from ZSDD portal.")
    parser.add_argument("--portal-url", default=DEFAULT_PORTAL_URL)
    parser.add_argument("--issue-url", action="append", default=[])
    parser.add_argument("--year")
    parser.add_argument("--issue")
    parser.add_argument("--content-id")
    parser.add_argument("--title")
    parser.add_argument("--web-id", default="zsdd")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--max-issues", type=int, default=0)
    parser.add_argument("--max-papers", type=int, default=1)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if bool(args.year) != bool(args.issue):
        parser.error("--year and --issue must be used together")
    if args.content_id and (args.year or args.issue):
        parser.error("--year/--issue cannot be used with --content-id")

    if args.year and args.issue:
        issue_dir = issue_directory_name(args.year, args.issue)
        if args.output_dir == DEFAULT_OUTPUT_DIR:
            args.output_dir = f"data/raw/zsdd/{issue_dir}/papers"
        if args.manifest == DEFAULT_MANIFEST:
            args.manifest = f"data/raw/zsdd/{issue_dir}/manifest.jsonl"

    if args.content_id:
        if not args.title:
            parser.error("--title is required with --content-id")
        papers = [
            Paper(
                content_id=args.content_id,
                download_type="1",
                web_id=args.web_id,
                title=args.title,
                source_page=args.portal_url,
            )
        ]
    elif args.year and args.issue:
        issue_url = resolve_issue_url(args.portal_url, year=args.year, issue=args.issue)
        papers = discover_papers(seed_urls=[issue_url], max_issues=0)
    else:
        seed_urls = [args.portal_url, *args.issue_url]
        papers = discover_papers(seed_urls=seed_urls, max_issues=args.max_issues)

    if args.max_papers >= 0:
        papers = papers[: args.max_papers]

    if args.dry_run:
        print(json.dumps([asdict(p) for p in papers], ensure_ascii=False, indent=2))
        return 0

    output_dir = Path(args.output_dir)
    manifest_path = Path(args.manifest)
    completed_ids = load_completed_paper_ids(manifest_path)
    for index, paper in enumerate(papers, start=1):
        path = output_path_for_paper(paper, output_dir)
        reason = skip_reason(paper.content_id, path, completed_ids)
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
            completed_ids.add(paper.content_id)
            print(json.dumps(record, ensure_ascii=False))
            continue

        record = download_pdf(paper, output_dir=output_dir)
        record["downloaded_at"] = int(time.time())
        write_manifest(record, manifest_path)
        completed_ids.add(paper.content_id)
        print(json.dumps(record, ensure_ascii=False))
        if index < len(papers) and args.sleep > 0:
            time.sleep(args.sleep)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, ValueError) as exc:
        print(f"download_zsdd.py: {exc}", file=sys.stderr)
        raise SystemExit(1)
