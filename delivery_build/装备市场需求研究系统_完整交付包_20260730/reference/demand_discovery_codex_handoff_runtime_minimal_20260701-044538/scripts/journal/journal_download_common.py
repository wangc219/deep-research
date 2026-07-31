"""Shared helpers for journal PDF collection scripts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from http.cookiejar import CookieJar
from http.client import IncompleteRead, RemoteDisconnected
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


SUCCESS_STATUSES = {"downloaded", "skipped_existing"}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
REQUEST_ATTEMPTS = 3


def safe_filename(name: str, suffix: str = ".pdf") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "untitled"
    if not cleaned.lower().endswith(suffix.lower()):
        cleaned += suffix
    return cleaned


def normalize_issue(issue: str) -> str:
    issue = issue.strip()
    if issue.isdigit():
        return issue.zfill(2)
    return issue.upper()


def issue_directory_name(year: str, issue: str) -> str:
    return f"{year.strip()}-{normalize_issue(issue)}"


def response_header(headers: dict[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return ""


def safe_header_value(value: str) -> str:
    return value.encode("ascii", errors="backslashreplace").decode("ascii")


def request_bytes(
    url: str,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
    timeout: int = 60,
) -> tuple[bytes, dict[str, str]]:
    last_error: URLError | IncompleteRead | RemoteDisconnected | TimeoutError | None = None
    for _attempt in range(REQUEST_ATTEMPTS):
        req = Request(url, data=data, headers=headers or {}, method=method)
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.read(), dict(resp.headers.items())
        except (URLError, IncompleteRead, RemoteDisconnected, TimeoutError) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError("request attempts must be positive")


def request_text(
    url: str,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
) -> str:
    content, response_headers = request_bytes(url, headers=headers, method=method, data=data)
    content_type = response_header(response_headers, "Content-Type")
    charset_match = re.search(r"charset=([^;]+)", content_type, re.I)
    encodings = [charset_match.group(1)] if charset_match else []
    encodings.extend(["utf-8", "gb18030"])
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def request_form_text(
    url: str,
    form: dict[str, str],
    referer: str,
    headers: dict[str, str] | None = None,
) -> str:
    request_headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": referer,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    if headers:
        request_headers.update(headers)
    return request_text(
        url,
        headers=request_headers,
        method="POST",
        data=urlencode(form).encode("utf-8"),
    )


def load_completed_paper_ids(manifest_path: Path) -> set[str]:
    completed: set[str] = set()
    if not manifest_path.exists():
        return completed

    with manifest_path.open("r", encoding="utf-8") as manifest:
        for line in manifest:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("status") not in SUCCESS_STATUSES:
                continue
            paper = record.get("paper")
            if not isinstance(paper, dict):
                continue
            paper_id = (
                paper.get("article_id")
                or paper.get("paper_id")
                or paper.get("content_id")
                or paper.get("id")
            )
            if paper_id:
                completed.add(str(paper_id))
    return completed


def skip_reason(
    paper_id: str,
    output_path: Path,
    completed_ids: set[str],
    force: bool = False,
) -> str | None:
    if force:
        return None
    if paper_id in completed_ids:
        return "manifest"
    if output_path.exists() and output_path.stat().st_size > 0:
        return "file_exists"
    return None


def write_manifest(record: dict[str, object], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as manifest:
        manifest.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_cookie_header(cookie: str | None = None, cookie_file: str | None = None) -> str:
    if cookie:
        return cookie.strip()
    if not cookie_file:
        return ""
    return Path(cookie_file).read_text(encoding="utf-8").strip()
