"""Batch-download configured journal issues into data/raw/<journal>/<year-issue>/."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote

import download_dzdkjs
import download_hkxb
import download_ktfy
import download_xxdkjs
import download_zsdd
from journal_download_common import (
    DEFAULT_USER_AGENT,
    issue_directory_name,
    normalize_issue,
    request_bytes,
    request_text,
    write_manifest,
)
from wanfang_journal_downloader import WanfangJournalConfig


WANFANG_YEAR_ISSUE_URL = "https://c.wanfangdata.com.cn/com.wanfangdata.miner.MagazineOtherService/yearIssue"


@dataclass(frozen=True)
class IssueTarget:
    journal_slug: str
    year: str
    issue: str


@dataclass(frozen=True)
class JournalSpec:
    slug: str
    name: str
    main: Callable[[list[str] | None], int]
    discover: Callable[[], list[IssueTarget]]


@dataclass
class IssueRunResult:
    status: str
    issue: IssueTarget
    exit_code: int
    downloaded_at: int


def _encode_varint(value: int) -> bytes:
    chunks: list[int] = []
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            chunks.append(byte | 0x80)
        else:
            chunks.append(byte)
            return bytes(chunks)


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValueError("truncated protobuf varint")


def _proto_string(field_number: int, value: str) -> bytes:
    payload = value.encode("utf-8")
    tag = (field_number << 3) | 2
    return _encode_varint(tag) + _encode_varint(len(payload)) + payload


def build_wanfang_year_issue_request(config: WanfangJournalConfig) -> bytes:
    message = _proto_string(1, config.journal_id) + _proto_string(2, config.journal_name)
    return b"\x00" + len(message).to_bytes(4, "big") + message


def _grpc_web_messages(response: bytes) -> list[bytes]:
    messages: list[bytes] = []
    offset = 0
    while offset + 5 <= len(response):
        frame_type = response[offset]
        frame_length = int.from_bytes(response[offset + 1 : offset + 5], "big")
        offset += 5
        if offset + frame_length > len(response):
            break
        frame = response[offset : offset + frame_length]
        offset += frame_length
        if frame_type & 0x80:
            continue
        messages.append(frame)
    return messages or [response]


def _iter_length_delimited(data: bytes) -> Iterable[tuple[int, bytes]]:
    offset = 0
    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if wire_type == 2:
            size, offset = _read_varint(data, offset)
            yield field_number, data[offset : offset + size]
            offset += size
        elif wire_type == 0:
            _value, offset = _read_varint(data, offset)
        else:
            raise ValueError(f"unsupported protobuf wire type: {wire_type}")


def _parse_wanfang_issue_group(group: bytes) -> tuple[str, list[str]] | None:
    year = ""
    issues: list[str] = []
    for field_number, value in _iter_length_delimited(group):
        text = value.decode("utf-8", errors="replace").strip()
        if field_number == 1:
            year = text
        elif field_number == 2:
            issues.append(normalize_issue(text))
    if not re.fullmatch(r"\d{4}", year) or not issues:
        return None
    return year, issues


def parse_wanfang_year_issue_response(response: bytes, journal_slug: str) -> list[IssueTarget]:
    targets: list[IssueTarget] = []
    seen: set[tuple[str, str]] = set()
    for message in _grpc_web_messages(response):
        for _field_number, group in _iter_length_delimited(message):
            parsed = _parse_wanfang_issue_group(group)
            if not parsed:
                continue
            year, issues = parsed
            for issue in issues:
                key = (year, issue)
                if key in seen:
                    continue
                seen.add(key)
                targets.append(IssueTarget(journal_slug=journal_slug, year=year, issue=issue))
    return targets


def discover_wanfang_issues(config: WanfangJournalConfig) -> list[IssueTarget]:
    body = build_wanfang_year_issue_request(config)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Content-Type": "application/grpc-web+proto",
        "X-Grpc-Web": "1",
        "X-User-Agent": "grpc-web-javascript/0.1",
        "Origin": "https://c.wanfangdata.com.cn",
        "Referer": f"https://c.wanfangdata.com.cn/magazine/{config.journal_id}",
    }
    response, _headers = request_bytes(
        WANFANG_YEAR_ISSUE_URL,
        headers=headers,
        method="POST",
        data=body,
    )
    return parse_wanfang_year_issue_response(response, journal_slug=config.output_slug)


def discover_zsdd_issues() -> list[IssueTarget]:
    html = download_zsdd.request_text(
        download_zsdd.DEFAULT_PORTAL_URL,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    return [
        IssueTarget("zsdd", issue.year, normalize_issue(issue.issue))
        for issue in download_zsdd.parse_issues(html)
    ]


def discover_ktfy_issues() -> list[IssueTarget]:
    try:
        payload = download_ktfy.request_form_json(
            "https://www.spacejournal.cn/ktfy/data/catalog/catalogMap",
            {"type": "1"},
            referer=download_ktfy.DEFAULT_ARCHIVE_URL,
        )
        issues = download_ktfy.parse_issues_from_catalog_map(payload)
    except (HTTPError, URLError, ValueError, json.JSONDecodeError):
        html = download_ktfy.request_text(
            download_ktfy.DEFAULT_ARCHIVE_URL,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        issues = download_ktfy.parse_issues(html)
    return [IssueTarget("ktfy", issue.year, normalize_issue(issue.issue)) for issue in issues]


def _parse_hkxb_years(html: str) -> list[str]:
    years = re.findall(r"showTenYearVolumnDetail\.do\?nian=(\d{4})", html)
    seen: set[str] = set()
    unique: list[str] = []
    for year in years:
        if year not in seen:
            seen.add(year)
            unique.append(year)
    return sorted(unique, reverse=True)


def discover_hkxb_issues() -> list[IssueTarget]:
    archive_html = request_text(download_hkxb.DEFAULT_ARCHIVE_URL, headers={"User-Agent": DEFAULT_USER_AGENT})
    years = _parse_hkxb_years(archive_html)
    issues: list[IssueTarget] = []
    if not years:
        return [
            IssueTarget("hkxb", issue.year, normalize_issue(issue.issue))
            for issue in download_hkxb.parse_issues(archive_html)
        ]
    for year in years:
        year_url = download_hkxb.YEAR_URL_TMPL.format(year=quote(year, safe=""))
        html = request_text(year_url, headers={"User-Agent": DEFAULT_USER_AGENT})
        issues.extend(
            IssueTarget("hkxb", issue.year, normalize_issue(issue.issue))
            for issue in download_hkxb.parse_issues(html)
            if issue.year == year
        )
    return _dedupe_issues(issues)


def configured_journals() -> dict[str, JournalSpec]:
    return {
        "zsdd": JournalSpec("zsdd", "战术导弹技术", download_zsdd.main, discover_zsdd_issues),
        "ktfy": JournalSpec("ktfy", "空天防御", download_ktfy.main, discover_ktfy_issues),
        "xxdkjs": JournalSpec(
            "xxdkjs",
            "信息对抗技术",
            download_xxdkjs.main,
            lambda: discover_wanfang_issues(download_xxdkjs.CONFIG),
        ),
        "dzdkjs": JournalSpec(
            "dzdkjs",
            "电子信息对抗技术",
            download_dzdkjs.main,
            lambda: discover_wanfang_issues(download_dzdkjs.CONFIG),
        ),
        "hkxb": JournalSpec("hkxb", "航空学报", download_hkxb.main, discover_hkxb_issues),
    }


def discover_all_issues(journal_slugs: Iterable[str] | None = None) -> list[IssueTarget]:
    specs = configured_journals()
    selected = list(journal_slugs or specs.keys())
    issues: list[IssueTarget] = []
    for slug in selected:
        issues.extend(specs[slug].discover())
    return _dedupe_issues(issues)


def _dedupe_issues(issues: Iterable[IssueTarget]) -> list[IssueTarget]:
    seen: set[IssueTarget] = set()
    unique: list[IssueTarget] = []
    for issue in issues:
        if issue in seen:
            continue
        seen.add(issue)
        unique.append(issue)
    return unique


def filter_issues(
    issues: Iterable[IssueTarget],
    journals: set[str] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    max_issues: int = -1,
) -> list[IssueTarget]:
    selected: list[IssueTarget] = []
    for issue in issues:
        year = int(issue.year)
        if journals and issue.journal_slug not in journals:
            continue
        if start_year is not None and year < start_year:
            continue
        if end_year is not None and year > end_year:
            continue
        selected.append(issue)
        if max_issues >= 0 and len(selected) >= max_issues:
            break
    return selected


def run_issue_download(
    issue: IssueTarget,
    max_papers: int = -1,
    paper_sleep: float = 1.0,
    cookie_file: str | None = None,
) -> IssueRunResult:
    specs = configured_journals()
    spec = specs[issue.journal_slug]
    issue_dir = issue_directory_name(issue.year, issue.issue)
    argv = [
        "--year",
        issue.year,
        "--issue",
        issue.issue,
        "--max-papers",
        str(max_papers),
        "--sleep",
        str(paper_sleep),
        "--output-dir",
        f"data/raw/{issue.journal_slug}/{issue_dir}/papers",
        "--manifest",
        f"data/raw/{issue.journal_slug}/{issue_dir}/manifest.jsonl",
    ]
    if cookie_file and issue.journal_slug in {"xxdkjs", "dzdkjs", "hkxb"}:
        argv.extend(["--cookie-file", cookie_file])

    exit_code = spec.main(argv)
    return IssueRunResult(
        status="ok" if exit_code == 0 else "failed",
        issue=issue,
        exit_code=exit_code,
        downloaded_at=int(time.time()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch download configured journal issues.")
    parser.add_argument("--journal", action="append", choices=sorted(configured_journals().keys()))
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--max-issues", type=int, default=-1)
    parser.add_argument("--max-papers-per-issue", type=int, default=-1)
    parser.add_argument("--paper-sleep", type=float, default=1.0)
    parser.add_argument("--issue-sleep", type=float, default=2.0)
    parser.add_argument("--cookie-file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--manifest", default="data/raw/journal_batch_manifest.jsonl")
    args = parser.parse_args(argv)

    journal_set = set(args.journal) if args.journal else None
    issues = filter_issues(
        discover_all_issues(args.journal),
        journals=journal_set,
        start_year=args.start_year,
        end_year=args.end_year,
        max_issues=args.max_issues,
    )

    if args.dry_run:
        print(json.dumps([asdict(issue) for issue in issues], ensure_ascii=False, indent=2))
        return 0

    failed = False
    for index, issue in enumerate(issues, start=1):
        try:
            result = run_issue_download(
                issue,
                max_papers=args.max_papers_per_issue,
                paper_sleep=args.paper_sleep,
                cookie_file=args.cookie_file,
            )
        except (HTTPError, URLError, ValueError, json.JSONDecodeError, RemoteDisconnected) as exc:
            failed = True
            result = IssueRunResult("failed", issue, 1, int(time.time()))
            record = asdict(result)
            record["error"] = str(exc)
            write_manifest(record, Path(args.manifest))
            print(json.dumps(record, ensure_ascii=False), file=sys.stderr)
            if args.strict:
                return 1
        else:
            failed = failed or result.exit_code != 0
            write_manifest(asdict(result), Path(args.manifest))
            print(json.dumps(asdict(result), ensure_ascii=False))
            if args.strict and result.exit_code != 0:
                return result.exit_code

        if index < len(issues) and args.issue_sleep > 0:
            time.sleep(args.issue_sleep)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
