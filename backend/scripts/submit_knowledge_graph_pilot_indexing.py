#!/usr/bin/env python3
"""以本地所有者身份提交 Pilot 全量待入库任务。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx


APP_ROOT = Path(__file__).resolve().parents[1]
for import_path in (APP_ROOT, APP_ROOT / "package"):
    value = str(import_path)
    if value not in sys.path:
        sys.path.insert(0, value)


def load_kb_id(path: Path) -> str:
    """从不含运维令牌的本地 Pilot 清单读取知识库 ID。"""

    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    kb_id = str((payload.get("knowledge_base") or {}).get("kb_id") or "")
    if not kb_id:
        raise ValueError("Pilot 访问清单缺少 knowledge_base.kb_id")
    return kb_id


async def submit(args: argparse.Namespace) -> dict[str, Any]:
    """读取真实待入库数，并通过公开 API 幂等提交一个续跑任务链。"""

    from platform_core.knowledge.training.local_pilot_operator import local_operator_headers

    kb_id = load_kb_id(args.pilot_access)
    headers, operator_uid = await local_operator_headers(args.api_base)
    async with httpx.AsyncClient(base_url=args.api_base.rstrip("/"), timeout=60) as client:
        current = await client.get("/knowledge/databases", headers=headers)
        current.raise_for_status()
        database = next(
            (item for item in current.json().get("databases") or [] if str(item.get("kb_id") or "") == kb_id),
            None,
        )
        if database is None:
            raise LookupError(f"本地 Pilot 知识库不存在: {kb_id}")
        pending_count = int((database.get("stats") or {}).get("pending_index_count") or 0)
        if args.dry_run or pending_count == 0:
            return {
                "contract_version": "defense-kg-pilot-index-submit-v1",
                "mode": "dry_run" if args.dry_run else "no_op",
                "kb_id": kb_id,
                "pending_index_count": pending_count,
                "operator_uid": operator_uid,
                "cloud_authorized": False,
            }
        response = await client.post(
            f"/knowledge/databases/{kb_id}/documents/index-pending",
            headers=headers,
            json={"params": {}},
        )
        response.raise_for_status()
        result = response.json()
        return {
            "contract_version": "defense-kg-pilot-index-submit-v1",
            "mode": "submitted",
            "kb_id": kb_id,
            "pending_index_count": pending_count,
            "queued_count": int(result.get("queued_count") or 0),
            "task_id": result.get("task_id"),
            "status": result.get("status"),
            "operator_uid": operator_uid,
            "cloud_authorized": False,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-access", type=Path, required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:5050/api")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        report = asyncio.run(submit(parse_args()))
    except Exception as exc:
        print(f"Pilot 入库提交失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
