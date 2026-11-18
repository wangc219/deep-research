#!/usr/bin/env python3
"""按预检路由提交 Pilot 原生文本与隔离 OCR 解析任务。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

PENDING_STATUSES = {"uploaded", "error_parsing", "failed"}
PARSED_STATUSES = {"parsed", "indexed"}
NATIVE_ROUTES = {"native_text", "complex_layout"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:5050/api")
    parser.add_argument(
        "--operator-mode",
        choices=("local-superadmin", "pilot-role"),
        default="local-superadmin",
        help="默认使用仅限 loopback 的短时本地所有者身份；pilot-role 仅兼容旧环境。",
    )
    parser.add_argument("--group", choices=("all", "native", "ocr"), default="all")
    parser.add_argument("--native-concurrency", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        report = asyncio.run(dispatch(args))
    except Exception as exc:
        print(f"Pilot 路由解析提交失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


async def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    """以独立运维身份提交任务，不放大标注账号权限。"""

    from platform_core.knowledge.training.local_pilot_operator import local_operator_headers

    routing = load_routing(args.preflight.expanduser().resolve())
    kb_id, uid, password = load_account(args.credentials.expanduser().resolve())
    with httpx.Client(base_url=args.api_base.rstrip("/"), timeout=60) as client:
        if args.operator_mode == "local-superadmin":
            headers, _operator_uid = await local_operator_headers(args.api_base)
        else:
            login = client.post("/auth/token", data={"username": uid, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        files = list_documents(client, kb_id, headers)
        groups = partition_pending_files(files, routing)
        submissions = []
        plans = (
            ("native", {"ocr_engine": "disable", "parse_concurrency": args.native_concurrency}),
            ("ocr", {"ocr_engine": "rapid_ocr", "parse_concurrency": 1}),
        )
        for group, params in plans:
            if args.group not in {"all", group}:
                continue
            file_ids = groups[group]
            if not file_ids:
                continue
            if args.dry_run:
                submissions.append({"group": group, "file_count": len(file_ids), "params": params, "status": "dry_run"})
                continue
            response = client.post(
                f"/knowledge/databases/{kb_id}/documents/parse",
                headers=headers,
                json={"file_ids": file_ids, "params": params},
            )
            response.raise_for_status()
            payload = response.json()
            submissions.append(
                {
                    "group": group,
                    "file_count": len(file_ids),
                    "params": params,
                    "status": payload.get("status"),
                    "task_id": payload.get("task_id"),
                }
            )
    return {
        "contract": "defense-kg-routed-parser-dispatch-v1",
        "kb_id": kb_id,
        "documents": len(files),
        "already_parsed": groups["already_parsed"],
        "pending_native": len(groups["native"]),
        "pending_ocr": len(groups["ocr"]),
        "submissions": submissions,
    }


def load_routing(path: Path) -> dict[str, str]:
    routes: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") != "succeeded":
            raise ValueError(f"预检包含失败文档: {row.get('document_id')}")
        filename = Path(str(row["path"])).name
        if filename in routes:
            raise ValueError(f"预检文件名重复: {filename}")
        routes[filename] = str(row["route"])
    if not routes:
        raise ValueError("解析预检清单为空")
    return routes


def load_account(path: Path) -> tuple[str, str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    kb_id = str((payload.get("knowledge_base") or {}).get("kb_id") or "")
    account = next((item for item in payload.get("accounts") or [] if item.get("pilot_role") == "annotator_a"), None)
    if not kb_id or not account:
        raise ValueError("本地 Pilot 凭据缺少知识库或标注员 A")
    return kb_id, str(account["uid"]), str(account["password"])


def list_documents(client: httpx.Client, kb_id: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    files = []
    page = 1
    while True:
        response = client.get(
            f"/knowledge/databases/{kb_id}/documents",
            headers=headers,
            params={"page": page, "page_size": 500, "recursive": "true"},
        )
        response.raise_for_status()
        payload = response.json()
        files.extend(item for item in payload["items"] if not item.get("is_folder"))
        if not payload.get("has_more"):
            return files
        page += 1


def partition_pending_files(files: list[dict[str, Any]], routing: dict[str, str]) -> dict[str, Any]:
    names = {str(item["filename"]) for item in files}
    missing = sorted(names - set(routing))
    unexpected = sorted(set(routing) - names)
    if missing or unexpected:
        raise ValueError(f"知识库与预检清单不一致，未路由 {missing[:5]}，未导入 {unexpected[:5]}")
    result: dict[str, Any] = {"native": [], "ocr": [], "already_parsed": 0}
    for item in files:
        status = str(item.get("status") or "")
        if status in PARSED_STATUSES:
            result["already_parsed"] += 1
            continue
        if status not in PENDING_STATUSES:
            raise ValueError(f"文件存在不可提交状态: {item['filename']}={status}")
        route = routing[str(item["filename"])]
        target = "native" if route in NATIVE_ROUTES else "ocr"
        result[target].append(str(item["file_id"]))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
