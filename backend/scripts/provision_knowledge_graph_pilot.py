"""通过本地公开 API 幂等准备知识图谱 Pilot 账号与独立知识库。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import stat
import string
import sys
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select


APP_ROOT = Path(__file__).resolve().parents[1]
for import_path in (APP_ROOT, APP_ROOT / "package"):
    import_path_str = str(import_path)
    if import_path_str not in sys.path:
        sys.path.insert(0, import_path_str)


ACCOUNT_SPECS = (
    {"username": "Pilot标注员A", "pilot_role": "annotator_a", "domain_batches": [1, 2]},
    {"username": "Pilot标注员B", "pilot_role": "annotator_b", "domain_batches": [3, 4]},
    {"username": "Pilot仲裁专家", "pilot_role": "arbitrator", "domain_batches": [5, 6]},
)


class ProvisionError(RuntimeError):
    """Pilot 准备失败。"""


def _new_password() -> str:
    """生成不依赖 shell 转义的本地一次性强密码。"""

    alphabet = string.ascii_letters + string.digits
    return "Kg!" + "".join(secrets.choice(alphabet) for _ in range(21))


def _pilot_share_config(account_uids: list[str]) -> dict[str, Any]:
    """仅授予标注账号读取权限，管理权由知识库所有者保留。"""

    return {
        "version": 2,
        "read_scope": {"access_level": "user", "user_uids": account_uids},
        "manage_scope": None,
    }


async def _load_existing_accounts() -> dict[str, dict[str, Any]]:
    """按固定显示名读取已存在账号，阻止静默覆盖密码。"""

    from platform_core.storage.postgres.manager import pg_manager
    from platform_core.storage.postgres.models_business import User

    usernames = [str(spec["username"]) for spec in ACCOUNT_SPECS]
    async with pg_manager.get_async_session_context() as session:
        result = await session.execute(select(User).where(User.username.in_(usernames)))
        users = list(result.scalars().all())
    return {
        user.username: {
            "id": int(user.id),
            "uid": user.uid,
            "role": user.role,
            "department_id": user.department_id,
            "is_deleted": int(user.is_deleted or 0),
        }
        for user in users
    }


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    token: str,
    json_body: dict[str, Any] | None = None,
) -> Any:
    """调用本地 API，并保留稳定错误语义。"""

    response = await client.request(
        method,
        path,
        headers={"Authorization": f"Bearer {token}"},
        json=json_body,
    )
    if response.is_error:
        detail = response.text[:1000]
        raise ProvisionError(f"{method} {path} 返回 {response.status_code}: {detail}")
    return response.json()


async def provision(args: argparse.Namespace) -> dict[str, Any]:
    """创建三账号、六批分工和独立中文 Pilot 知识库。"""

    from platform_core.knowledge.training.local_pilot_operator import local_operator_headers

    if args.output.exists():
        raise ProvisionError(f"凭据文件已存在，拒绝覆盖: {args.output}")

    try:
        headers, superadmin_uid = await local_operator_headers(args.api_base)
    except (RuntimeError, ValueError) as exc:
        raise ProvisionError(str(exc)) from exc
    existing_accounts = await _load_existing_accounts()
    if existing_accounts and not args.recover_created_accounts:
        names = "、".join(sorted(existing_accounts))
        raise ProvisionError(f"Pilot 账号已存在但没有可重放明文密码，拒绝静默接管: {names}")

    token = headers["Authorization"].removeprefix("Bearer ")
    created_accounts: list[dict[str, Any]] = []
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(base_url=args.api_base.rstrip("/"), timeout=timeout) as client:
        for spec in ACCOUNT_SPECS:
            password = _new_password()
            existing = existing_accounts.get(str(spec["username"]))
            if existing is None:
                created = await _request_json(
                    client,
                    "POST",
                    "/auth/users",
                    token=token,
                    json_body={
                        "username": spec["username"],
                        "password": password,
                        "role": "user",
                        "department_id": args.department_id,
                    },
                )
            else:
                if existing["is_deleted"] or existing["role"] != "user":
                    raise ProvisionError(f"已有账号状态不符合 Pilot 约束: {spec['username']}")
                created = await _request_json(
                    client,
                    "PUT",
                    f"/auth/users/{existing['id']}",
                    token=token,
                    json_body={"password": password},
                )
            created_accounts.append(
                {
                    "username": str(created["username"]),
                    "uid": str(created["uid"]),
                    "password": password,
                    "role": str(created["role"]),
                    "department_id": created.get("department_id"),
                    "pilot_role": spec["pilot_role"],
                    "domain_batches": spec["domain_batches"],
                }
            )

        account_uids = [str(account["uid"]) for account in created_accounts]
        databases_payload = await _request_json(client, "GET", "/knowledge/databases", token=token)
        databases = list(databases_payload.get("databases") or [])
        existing_kb = next((item for item in databases if str(item.get("name")) == args.kb_name), None)
        if existing_kb is not None:
            raise ProvisionError(f"同名 Pilot 知识库已存在，拒绝复用不明状态: {existing_kb.get('kb_id')}")

        database = await _request_json(
            client,
            "POST",
            "/knowledge/databases",
            token=token,
            json_body={
                "database_name": args.kb_name,
                "description": args.kb_description,
                "embedding_model_spec": args.embedding_model_spec,
                "kb_type": "milvus",
                "additional_params": {
                    "auto_generate_questions": False,
                    "pilot_contract": {
                        "corpus_size": 999,
                        "paper_count": 999,
                        "patent_count": 0,
                        "acceptance_language": "zh",
                        "gold_split": {"train": 210, "dev": 30, "test": 60},
                    },
                },
                "share_config": _pilot_share_config(account_uids),
            },
        )

    return {
        "contract_version": "defense-kg-local-pilot-access-v1",
        "environment": "local",
        "cloud_authorized": False,
        "operator_uid": superadmin_uid,
        "knowledge_base": {
            "kb_id": str(database["kb_id"]),
            "name": str(database["name"]),
            "kb_type": str(database["kb_type"]),
            "acceptance_language": "zh",
            "corpus_size": 999,
        },
        "accounts": created_accounts,
        "assignment_note": "领域初筛每人两个批次；正式 300 篇金标仍由 A/B 独立双标，仲裁专家只处理分歧。",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:5050/api")
    parser.add_argument("--department-id", type=int, default=1)
    parser.add_argument("--kb-name", default="军事装备知识图谱Pilot-999-中文")
    parser.add_argument(
        "--kb-description",
        default="项目 LLM + LightRAG 本地中文 Pilot；999 篇论文，云端未授权。",
    )
    parser.add_argument("--embedding-model-spec", default="siliconflow-cn:Pro/BAAI/bge-m3")
    parser.add_argument(
        "--recover-created-accounts",
        action="store_true",
        help="仅用于本脚本在写凭据前中断后的本地恢复；会轮换同名 Pilot 账号密码。",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = asyncio.run(provision(args))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.output.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception as exc:
        print(f"Pilot 本地准备失败：{exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "created",
                "kb_id": payload["knowledge_base"]["kb_id"],
                "account_uids": [item["uid"] for item in payload["accounts"]],
                "credentials_file": os.fspath(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
