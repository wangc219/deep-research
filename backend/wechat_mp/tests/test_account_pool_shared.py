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


def test_multiple_pool_instances_rotate_two_active_accounts_fairly(monkeypatch, tmp_path):
    """共享池连续借用必须轮换账号，不能让所有用户 Worker 固定命中首账号。"""
    target = tmp_path / "shared" / "account_pool.json"
    monkeypatch.setattr(module, "ACCOUNT_POOL_FILE", target)
    monkeypatch.setattr(module.AccountPool, "_try_find_local_session", lambda self: None)

    writer = module.AccountPool()
    for index in range(2):
        writer.add_or_update(
            {
                "vid": str(939000000 + index),
                "accessToken": f"token-{index}",
                "deviceId": f"device-{index}",
                "deviceName": "Test Device",
            }
        )

    accounts = json.loads(target.read_text())
    for account in accounts:
        account["last_used"] = 0
    target.write_text(json.dumps(accounts), encoding="utf-8")

    clock = iter((1000.0, 1001.0, 1002.0))
    monkeypatch.setattr(module.time, "time", lambda: next(clock))

    first = module.AccountPool().acquire()
    second = module.AccountPool().acquire()
    third = module.AccountPool().acquire()

    assert first["id"] != second["id"]
    assert third["id"] == first["id"]


def test_failed_active_account_reenters_rotation_after_bounded_penalty(monkeypatch, tmp_path):
    """一次普通失败只应暂缓账号，不能让双账号池永久退化成单账号。"""
    target = tmp_path / "shared" / "account_pool.json"
    monkeypatch.setattr(module, "ACCOUNT_POOL_FILE", target)
    monkeypatch.setattr(module.AccountPool, "_try_find_local_session", lambda self: None)

    writer = module.AccountPool()
    for index in range(2):
        writer.add_or_update(
            {
                "vid": str(939100000 + index),
                "accessToken": f"token-{index}",
                "deviceId": f"device-{index}",
                "deviceName": "Test Device",
            }
        )

    accounts = json.loads(target.read_text())
    failed_id = accounts[0]["id"]
    healthy_id = accounts[1]["id"]
    accounts[0]["last_used"] = 1000.0
    accounts[0]["failures"] = 1
    accounts[1]["last_used"] = 1000.0
    target.write_text(json.dumps(accounts), encoding="utf-8")

    clock = iter((1001.0, 1016.0, 1017.0))
    monkeypatch.setattr(module.time, "time", lambda: next(clock))

    assert module.AccountPool().acquire()["id"] == healthy_id
    assert module.AccountPool().acquire()["id"] == healthy_id
    assert module.AccountPool().acquire()["id"] == failed_id
