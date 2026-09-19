"""CLI channel for server-owned conversation sessions.

Usage: python -m equipment_deep_research.interfaces.dialogue_cli --run-id RUN
       --session-id SESSION [--message TEXT | --message-file PATH] [--wait]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


class DialogueAPIError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        # Session endpoints have stable URLs. Never forward authentication or
        # scope headers to a redirect destination.
        return None


urlopen = build_opener(_NoRedirect()).open


def _request(base: str, path: str, headers: dict[str, str], body=None):
    request = Request(
        base.rstrip("/") + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={**headers, **({"Content-Type": "application/json"} if body is not None else {})},
        method="POST" if body is not None else "GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        # Server errors may contain local paths or upstream provider details.
        # Status and operation suffice; never print headers or raw bodies.
        raise DialogueAPIError(f"Dialogue API returned HTTP {exc.code}") from None
    except (URLError, OSError, ValueError):
        raise DialogueAPIError("Dialogue API unavailable or returned invalid JSON") from None
    if not isinstance(result, dict):
        raise DialogueAPIError("Dialogue API returned an invalid response")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read or continue an existing conversation session.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--session-id", required=True)
    messages = parser.add_mutually_exclusive_group()
    messages.add_argument("--message", help="Message text; use '-' to read stdin.")
    messages.add_argument("--message-file", type=Path)
    parser.add_argument("--branch-id", default="main")
    parser.add_argument("--skill", action="append", default=None)
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--wait-timeout", type=float, default=300)
    parser.add_argument("--token-env", default="EQUIPMENT_DR_API_TOKEN")
    for scope in ("tenant", "workspace", "project", "profile"):
        parser.add_argument(f"--{scope}-id", default="")
    args = parser.parse_args(argv)
    parsed_base = urlsplit(args.api_base)
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc or parsed_base.username or parsed_base.password or parsed_base.query or parsed_base.fragment:
        parser.error("--api-base must be an HTTP(S) URL without credentials, query or fragment")
    if not 0 < args.wait_timeout <= 3600:
        parser.error("--wait-timeout must be between 0 and 3600 seconds")
    headers = {"X-Role": "analyst"}
    for scope in ("tenant", "workspace", "project", "profile"):
        value = getattr(args, f"{scope}_id")
        if value:
            headers[f"X-{scope.title()}-ID"] = value
    token = os.environ.get(args.token_env, "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    path = f"/runs/{quote(args.run_id, safe='')}/deep-thinking/sessions/{quote(args.session_id, safe='')}"
    failed_job = False
    try:
        if args.message is None and args.message_file is None:
            result = _request(args.api_base, path, headers)
        else:
            if args.message_file is not None:
                content = args.message_file.read_text(encoding="utf-8")
            else:
                content = sys.stdin.read() if args.message == "-" else args.message
            if not content or not content.strip():
                parser.error("message must not be empty")
            body = {"content": content, "branch_id": args.branch_id, "channel": "cli"}
            if args.skill is not None:
                body["active_skill_ids"] = args.skill
            headers["Idempotency-Key"] = args.idempotency_key or f"cli-{uuid4().hex}"
            result = _request(args.api_base, path + "/messages", headers, body)
            if args.wait:
                queued_job = result.get("job")
                job_id = queued_job.get("job_id") if isinstance(queued_job, dict) else None
                if not job_id:
                    raise DialogueAPIError("Dialogue API did not return a job id")
                job_path = f"/runs/{quote(args.run_id, safe='')}/deep-thinking/jobs/{quote(str(job_id), safe='')}"
                deadline = time.monotonic() + args.wait_timeout
                while True:
                    snapshot = _request(args.api_base, job_path, headers)
                    job = snapshot.get("job", snapshot)
                    if not isinstance(job, dict):
                        raise DialogueAPIError("Dialogue API returned an invalid job")
                    status = job.get("status")
                    if status in {"completed", "partial", "failed", "cancelled", "blocked", "interrupted"}:
                        failed_job = status != "completed"
                        result = {"job": job, **_request(args.api_base, path, headers)}
                        break
                    if time.monotonic() >= deadline:
                        raise DialogueAPIError(f"Wait timed out; job {job_id} remains on the server")
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if failed_job else 0
    except (DialogueAPIError, OSError, UnicodeError) as exc:
        print(str(exc) if isinstance(exc, DialogueAPIError) else "Could not read message file", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
