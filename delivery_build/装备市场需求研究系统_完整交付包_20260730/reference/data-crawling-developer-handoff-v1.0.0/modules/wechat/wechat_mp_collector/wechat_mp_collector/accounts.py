from __future__ import annotations

from typing import Any


DEFAULT_ACCOUNTS: list[dict[str, Any]] = [
    {
        "nickname": "防务快讯",
        "alias": "",
        "fakeid": "MzUxMTAyNzc0NQ==",
        "signature": "关注指挥信息系统发展，提供指挥信息系统最新动态。",
    },
    {
        "nickname": "军民融合观察",
        "alias": "JMRHGC",
        "fakeid": "MzU0OTI0OTM5Nw==",
        "signature": "远望智库旗下军民融合领域前沿资讯平台",
    },
]


def accounts_by_name(names: list[str] | None = None) -> list[dict[str, Any]]:
    if not names:
        return [dict(account) for account in DEFAULT_ACCOUNTS]

    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in names:
        account = find_account(name)
        if account is None:
            missing.append(name)
        else:
            selected.append(account)

    if missing:
        available = ", ".join(account["nickname"] for account in DEFAULT_ACCOUNTS)
        raise KeyError(f"unknown account(s): {', '.join(missing)}; available: {available}")
    return selected


def find_account(name: str) -> dict[str, Any] | None:
    normalized = name.strip()
    for account in DEFAULT_ACCOUNTS:
        if normalized in {account.get("nickname", ""), account.get("alias", ""), account.get("fakeid", "")}:
            return dict(account)
    return None

