"""真实 Redis 上验证多个 worker 的检索排队、合并与限流恢复。"""

import multiprocessing
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from platform_core.services.web_search_coordinator import SearchCoordinator, get_active_search_coordinator
from platform_core.storage.redis import RedisConfig, create_sync_redis_client

pytestmark = pytest.mark.integration


@pytest.fixture
def shared_search_state(monkeypatch):
    """每个测试使用独立的 Redis key 空间。"""
    monkeypatch.setenv("WEB_SEARCH_MIN_INTERVAL_SECONDS", "0.02")
    client = create_sync_redis_client(RedisConfig.from_env(socket_timeout=3, socket_connect_timeout=3))
    prefix = f"pytest:search:{uuid.uuid4().hex}"
    try:
        yield client, prefix
    finally:
        keys = list(client.scan_iter(f"{prefix}:*"))
        if keys:
            client.delete(*keys)
        client.close()


def _worker_search(prefix: str, query: str, provider: str = "open-websearch") -> dict:
    """独立 worker 模拟只允许一个在途请求的供应商。"""
    client = create_sync_redis_client(RedisConfig.from_env(socket_timeout=3, socket_connect_timeout=3))
    try:

        def backend():
            active = client.incr(f"{prefix}:active")
            client.rpush(f"{prefix}:observed", active)
            client.incr(f"{prefix}:requests")
            try:
                time.sleep(0.08)
                if active > 1:
                    return {"results": [], "status": "rate_limited", "retry_after_seconds": 1}
                return {"results": [{"title": query, "url": "https://example.org/evidence"}]}
            finally:
                client.decr(f"{prefix}:active")

        return SearchCoordinator(client, prefix=prefix, wait_seconds=10).run(provider, {"query": query}, backend)
    finally:
        client.close()


def test_three_independent_workers_share_one_public_exit_and_all_receive_evidence(shared_search_state):
    client, prefix = shared_search_state
    with ProcessPoolExecutor(3, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [
            pool.submit(_worker_search, prefix, f"domain {index}", provider)
            for index, provider in enumerate(["open-websearch", "public", "open-websearch"])
        ]
        results = [future.result(timeout=30) for future in futures]
    assert all(result["results"] for result in results)
    assert int(client.get(f"{prefix}:requests")) == 3
    assert max(map(int, client.lrange(f"{prefix}:observed", 0, -1))) == 1


def test_same_query_across_three_processes_is_sent_once(shared_search_state):
    client, prefix = shared_search_state
    with ProcessPoolExecutor(3, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(_worker_search, [prefix] * 3, ["radar drone"] * 3))
    assert int(client.get(f"{prefix}:requests")) == 1
    assert all(result["results"] for result in results)
    assert sum(bool(result.get("shared_cache_hit")) for result in results) == 2


def test_short_rate_limit_is_recovered_after_cooldown(shared_search_state):
    client, prefix = shared_search_state
    calls = []

    def backend():
        calls.append(time.monotonic())
        if len(calls) == 1:
            return {"status": "rate_limited", "retry_after_seconds": 1, "results": []}
        return {"results": [{"title": "recovered evidence"}]}

    result = SearchCoordinator(client, prefix=prefix, wait_seconds=3).run("public", {"query": "radar drone"}, backend)
    assert result["results"]
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.99
    assert result["queue_wait_seconds"] >= 0.9
    cached = SearchCoordinator(client, prefix=prefix).run("public", {"query": "radar drone"}, backend)
    assert cached["shared_cache_hit"] is True
    assert cached["queue_wait_seconds"] < 0.1
    assert len(calls) == 2


def test_long_cooldown_is_shared_and_not_retried_beyond_wait_budget(shared_search_state):
    client, prefix = shared_search_state
    calls = []

    def backend():
        calls.append(True)
        return {"status": "rate_limited", "retry_after_seconds": 10, "results": []}

    first = SearchCoordinator(client, prefix=prefix, wait_seconds=0.1).run("open-websearch", {"query": "one"}, backend)
    second = SearchCoordinator(client, prefix=prefix, wait_seconds=0.1).run("public", {"query": "two"}, backend)
    assert first["status"] == second["status"] == "rate_limited"
    assert len(calls) == 1
    assert second["retry_after_seconds"] >= 9


def test_partial_engine_limit_keeps_healthy_engine_available(shared_search_state):
    client, prefix = shared_search_state
    coordinator = SearchCoordinator(client, prefix=prefix)
    result = coordinator.run(
        "open-websearch",
        {"query": "one"},
        lambda: {
            "results": [{"title": "healthy engine evidence"}],
            "partial_failures": [{"engine": "bing", "status_code": 429, "retry_after_seconds": 10}],
        },
    )
    assert result["results"]
    assert coordinator.engine_remaining("bing") >= 9
    assert coordinator.engine_remaining("duckduckgo") == 0

    def backend():
        active = get_active_search_coordinator()
        assert active.engine_remaining("bing") > 0
        assert active.engine_remaining("duckduckgo") == 0
        return {"results": [{"title": "next domain evidence"}]}

    assert coordinator.run("open-websearch", {"query": "two"}, backend)["results"]


def test_antibot_is_not_retried_and_other_worker_fallback_shares_engine_cooldown(shared_search_state, monkeypatch):
    """真实 Redis 保证 daemon 的挑战在另一 worker 的直连兜底中仍被跳过。"""
    from platform_core.agents.toolkits.buildin import tools

    client, prefix = shared_search_state
    monkeypatch.setenv("OPEN_WEBSEARCH_URL", "http://search.test")
    monkeypatch.setenv("OPEN_WEBSEARCH_ENGINES", "bing,duckduckgo")
    coordinator = SearchCoordinator(client, prefix=prefix, wait_seconds=1)
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "status": "ok",
        "data": {
            "engines": ["bing", "duckduckgo"],
            "results": [],
            "partialFailures": [
                {"engine": "bing", "message": "CAPTCHA required"},
                {"engine": "duckduckgo", "message": "bot challenge"},
            ],
        },
    }
    with patch("httpx.Client.post", return_value=response) as post:
        result = coordinator.run(
            "open-websearch",
            {"query": "radar signal lookup"},
            lambda: tools._open_websearch.func(query="radar signal lookup"),
        )
        assert result["status"] == "blocked"
        assert post.call_count == 1
        assert coordinator.engine_remaining("bing") > 290
        assert coordinator.engine_remaining("duckduckgo") > 290

        # 新实例模拟另一 worker；两个冷却引擎均不得经 daemon 再发请求。
        other_worker = SearchCoordinator(client, prefix=prefix, wait_seconds=1)
        result = other_worker.run(
            "open-websearch",
            {"query": "different query"},
            lambda: tools._open_websearch.func(query="different query"),
        )
        assert not result["results"]
        assert post.call_count == 1

    # 直连 fallback 只允许尚未冷却的搜狗，不能绕过 daemon 的同引擎冷却。
    empty = MagicMock(status_code=200, text="<html>No results</html>")
    with patch("httpx.Client.get", return_value=empty) as get:
        other_worker.run(
            "public",
            {"query": "radar signal lookup"},
            lambda: tools._public_search.func(query="radar signal lookup"),
        )
    assert get.call_count == 1
    assert get.call_args.args[0] == tools._SOGOU_SEARCH_URL


def test_partial_challenge_cools_only_failed_engine_without_repeating_healthy_empty(shared_search_state):
    client, prefix = shared_search_state
    coordinator = SearchCoordinator(client, prefix=prefix, wait_seconds=1)
    calls = []

    def backend():
        calls.append(True)
        return {
            "status": "empty",
            "results": [],
            "partial_failures": [{"engine": "bing", "message": "captcha required"}],
        }

    result = coordinator.run("open-websearch", {"query": "narrow topic"}, backend)
    assert result["status"] == "empty"
    assert len(calls) == 1
    assert coordinator.engine_remaining("bing") > 290
    assert coordinator.engine_remaining("duckduckgo") == 0
