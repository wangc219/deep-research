"""通过本地公开 API 可恢复地导入知识图谱 Pilot 来源语料。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx


TRANSIENT_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class ImportError(RuntimeError):
    """Pilot 语料导入失败。"""


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ImportError("Pilot 来源清单为空")
    return rows


def _load_account(credentials_path: Path, pilot_role: str) -> tuple[str, str, str]:
    payload = json.loads(credentials_path.read_text(encoding="utf-8"))
    kb_id = str((payload.get("knowledge_base") or {}).get("kb_id") or "")
    account = next((item for item in payload.get("accounts") or [] if item.get("pilot_role") == pilot_role), None)
    if not kb_id or not account:
        raise ImportError("本地 Pilot 凭据缺少知识库或指定角色")
    return kb_id, str(account["uid"]), str(account["password"])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    file_path: Path | None = None,
    attempts: int = 4,
) -> httpx.Response:
    """对确定性请求执行有界瞬时错误重试。"""
    last_response: httpx.Response | None = None
    for attempt in range(1, attempts + 1):
        try:
            if file_path is None:
                response = await client.request(method, path, headers=headers, json=json_body)
            else:
                with file_path.open("rb") as source:
                    response = await client.request(
                        method,
                        path,
                        headers=headers,
                        files={"file": (file_path.name, source, "application/pdf")},
                    )
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.TimeoutException):
            if attempt == attempts:
                raise
            await asyncio.sleep(min(2 ** (attempt - 1), 8))
            continue

        last_response = response
        if response.status_code not in TRANSIENT_STATUS_CODES or attempt == attempts:
            return response
        await asyncio.sleep(min(2 ** (attempt - 1), 8))
    if last_response is None:
        raise ImportError(f"{method} {path} 未返回响应")
    return last_response


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """校验来源哈希、上传 MinIO，并逐篇提交权威文件记录。"""
    from platform_core.knowledge.training.local_pilot_operator import local_operator_headers

    manifest_path = args.manifest.expanduser().resolve()
    credentials_path = args.credentials.expanduser().resolve()
    checkpoint_path = args.checkpoint.expanduser().resolve()
    rows = _load_jsonl(manifest_path)
    kb_id, uid, password = _load_account(credentials_path, args.pilot_role)
    completed = {
        str(row["content_sha256"])
        for row in _load_jsonl(checkpoint_path)
        if row.get("status") in {"added", "already_present"}
    } if checkpoint_path.is_file() else set()
    pending = [row for row in rows if str(row["content_sha256"]) not in completed]
    if args.limit:
        pending = pending[: args.limit]
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    timeout = httpx.Timeout(connect=30.0, read=180.0, write=180.0, pool=30.0)
    limits = httpx.Limits(max_connections=max(args.concurrency * 2, 8), max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.api_base.rstrip("/"), timeout=timeout, limits=limits) as client:
        if args.operator_mode == "local-superadmin":
            headers, _operator_uid = await local_operator_headers(args.api_base, expires_minutes=180)
        else:
            login = await client.post("/auth/token", data={"username": uid, "password": password})
            if login.is_error:
                raise ImportError(f"Pilot 账号登录失败: {login.status_code} {login.text[:500]}")
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        write_lock = asyncio.Lock()
        progress_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(args.concurrency)
        state = {"processed": len(completed), "added": 0, "already_present": 0, "failed": 0}

        async def import_one(row: dict[str, Any]) -> None:
            async with semaphore:
                path = Path(str(row["path"])).expanduser().resolve()
                expected_hash = str(row["content_sha256"])
                if not path.is_file():
                    raise ImportError(f"来源文件不存在: {path}")
                if _sha256_file(path) != expected_hash:
                    raise ImportError(f"来源 SHA-256 已变化: {path.name}")

                upload = await _request(
                    client,
                    "POST",
                    f"/knowledge/files/upload?kb_id={kb_id}",
                    headers=headers,
                    file_path=path,
                )
                if upload.status_code == 409:
                    result = {
                        "document_id": row["document_id"],
                        "content_sha256": expected_hash,
                        "filename": row["filename"],
                        "status": "already_present",
                    }
                else:
                    if upload.is_error:
                        raise ImportError(f"上传失败 {path.name}: {upload.status_code} {upload.text[:500]}")
                    uploaded = upload.json()
                    minio_url = str(uploaded.get("file_path") or uploaded.get("minio_path") or "")
                    if not minio_url:
                        raise ImportError(f"上传响应缺少 MinIO URL: {path.name}")
                    add = await _request(
                        client,
                        "POST",
                        f"/knowledge/databases/{kb_id}/documents/add",
                        headers=headers,
                        json_body={
                            "items": [minio_url],
                            "params": {
                                "content_type": "file",
                                "source_type": str(row.get("source_type") or "paper"),
                                "language": str(row.get("language") or "zh"),
                                "domain": str(row.get("domain") or ""),
                                "source_manifest_document_id": str(row["document_id"]),
                                "source_manifest_version": str(row.get("manifest_version") or ""),
                                "acceptance_languages": list(row.get("acceptance_languages") or ["zh"]),
                                "content_hashes": {minio_url: expected_hash},
                                "file_sizes": {minio_url: int(row["file_size"])},
                                "source_paths": {minio_url: str(row["filename"])},
                                "auto_index": False,
                            },
                        },
                        attempts=1,
                    )
                    if add.is_error:
                        raise ImportError(f"登记失败 {path.name}: {add.status_code} {add.text[:500]}")
                    add_payload = add.json()
                    if int(add_payload.get("added") or 0) != 1:
                        detail = json.dumps(add_payload, ensure_ascii=False)[:500]
                        raise ImportError(f"登记未成功 {path.name}: {detail}")
                    result = {
                        "document_id": row["document_id"],
                        "content_sha256": expected_hash,
                        "filename": row["filename"],
                        "status": "added",
                        "file_id": add_payload["items"][0]["file_id"],
                    }

                async with write_lock:
                    with checkpoint_path.open("a", encoding="utf-8") as checkpoint:
                        checkpoint.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
                        checkpoint.flush()
                async with progress_lock:
                    state["processed"] += 1
                    state[result["status"]] += 1
                    if state["processed"] % args.progress_every == 0 or state["processed"] == len(rows):
                        print(
                            f"已导入 {state['processed']}/{len(rows)}，"
                            f"新增 {state['added']}，已存在 {state['already_present']}",
                            flush=True,
                        )

        results = await asyncio.gather(*(import_one(row) for row in pending), return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        state["failed"] = len(failures)
        if failures:
            examples = [str(item) for item in failures[:10]]
            raise ImportError(f"本轮 {len(failures)} 篇失败: {examples}")

        databases = await _request(client, "GET", "/knowledge/databases", headers=headers)
        databases.raise_for_status()
        database = next(item for item in databases.json()["databases"] if item["kb_id"] == kb_id)
        checkpoint_documents = len(completed) + len(pending)
        return {
            "status": "completed" if checkpoint_documents == len(rows) else "partial",
            "kb_id": kb_id,
            "manifest_documents": len(rows),
            "checkpoint_documents": checkpoint_documents,
            "this_run": state,
            "database_stats": {
                "file_count": database.get("file_count"),
                "pending_parse_count": database.get("pending_parse_count"),
                "failed_count": database.get("failed_count"),
            },
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--pilot-role", default="annotator_a", choices=["annotator_a", "annotator_b", "arbitrator"])
    parser.add_argument("--api-base", default="http://127.0.0.1:5050/api")
    parser.add_argument(
        "--operator-mode",
        choices=["local-superadmin", "pilot-role"],
        default="local-superadmin",
        help="默认使用仅限 loopback 的短时本地所有者身份；pilot-role 仅用于兼容旧环境。",
    )
    parser.add_argument("--concurrency", type=int, default=3, choices=range(1, 9))
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 个待导入来源；0 表示全部。")
    parser.add_argument("--progress-every", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = asyncio.run(run(args))
    except Exception as exc:
        print(f"Pilot 语料导入失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
