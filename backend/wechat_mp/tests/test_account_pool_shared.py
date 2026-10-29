"""共享微信读书账号池的并发持久化。"""

import json
from concurrent.futures import ThreadPoolExecutor

from backend import account_pool as module


def test_multiple_pool_instances_do_not_lose_concurrent_updates(monkeypatch, tmp_path):
    """多个用户 Worker 并发写入时必须保留每一次账号更新。"""
    target = tmp_path / "shared" / "account_pool.json"
    monkeypatch.setattr(module, "ACCOUNT_POOL_FILE", target)
    monkeypatch.setattr(module.AccountPool, "_try_find_local_session", lambda self: None)

    def add(index):
        pool = module.AccountPool()
        pool.add_or_update(
            {
                "vid": str(900000000 + index),
                "accessToken": f"token-{index}",
                "deviceId": f"device-{index}",
                "deviceName": "Test Device",
            }
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(add, range(24)))

    accounts = json.loads(target.read_text())
    assert {account["vid"] for account in accounts} == {str(900000000 + index) for index in range(24)}
    assert target.stat().st_mode & 0o777 == 0o600
    assert not list(target.parent.glob("*.tmp"))
