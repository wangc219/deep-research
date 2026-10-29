"""跨 worker 协调公开检索，控制并发、重复请求与供应商冷却。"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from email.utils import parsedate_to_datetime

from redis.exceptions import RedisError

from platform_core.storage.redis import RedisConfig, sync_redis_client

_ACQUIRE = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
local available = math.max(tonumber(redis.call('HGET', KEYS[1], 'lease_until') or '0'),
                          tonumber(redis.call('HGET', KEYS[1], 'next_start') or '0'),
                          tonumber(redis.call('HGET', KEYS[1], 'cool_until') or '0'))
if available > now then return available - now end
redis.call('HSET', KEYS[1], 'token', ARGV[1], 'lease_until', now + ARGV[2], 'next_start', now + ARGV[3])
redis.call('PEXPIRE', KEYS[1], ARGV[2] + ARGV[3])
return 0
"""
_RELEASE = """
if redis.call('HGET', KEYS[1], 'token') == ARGV[1] then
    redis.call('HDEL', KEYS[1], 'token', 'lease_until')
    return 1
end
return 0
"""
_UNLOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""
_COOL_DOWN = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
local until_time = math.max(tonumber(redis.call('HGET', KEYS[1], 'cool_until') or '0'), now + ARGV[1])
redis.call('HSET', KEYS[1], 'cool_until', until_time)
redis.call('PEXPIRE', KEYS[1], math.max(redis.call('PTTL', KEYS[1]), until_time - now + 180000))
return until_time - now
"""
_REMAINING = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
return math.max(0, tonumber(redis.call('HGET', KEYS[1], 'cool_until') or '0') - now)
"""
_ACTIVE: ContextVar[SearchCoordinator | None] = ContextVar("web_search_coordinator", default=None)


def get_active_search_coordinator() -> SearchCoordinator | None:
    """供供应商适配器读取当前请求的共享调度器。"""
    return _ACTIVE.get()


def search_failure(exc: Exception) -> dict:
    """保留限流状态及 Retry-After，避免只传字符串丢失恢复信息。"""
    result = {"results": [], "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    response = getattr(exc, "response", None)
    if response is not None:
        result["status_code"] = response.status_code
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                try:
                    delay = parsedate_to_datetime(retry_after).timestamp() - time.time()
                except (TypeError, ValueError, OverflowError):
                    delay = 30.0
            result["retry_after_seconds"] = max(1.0, delay)
    if result.get("status_code") == 429:
        result["status"] = "rate_limited"
    return result


def rate_limit_delay(result: dict) -> float:
    """仅从失败字段识别限流，避免把论文标题中的 429 当成故障。"""
    detail = " ".join(str(result.get(field) or "") for field in ("error", "message", "code")).casefold()
    limited = result.get("status_code") == 429 or result.get("status") == "rate_limited"
    limited = limited or any(
        marker in detail
        for marker in (
            "429",
            "too many requests",
            "toomanyrequests",
            "too_many_requests",
            "rate limit",
            "ratelimit",
            "rate_limit",
            "throttl",
            "限流",
        )
    )
    if not limited:
        return 0.0
    try:
        return max(1.0, float(result.get("retry_after_seconds") or 30.0))
    except (ValueError, TypeError):
        return 30.0


def antibot_delay(result: dict) -> float:
    """识别搜索入口的访问挑战，独立于短期限流执行较长冷却。"""
    detail = " ".join(str(result.get(field) or "") for field in ("error", "message", "code")).casefold()
    blocked = result.get("status_code") == 403 or result.get("status") == "blocked"
    blocked = blocked or any(
        marker in detail
        for marker in (
            "captcha",
            "anti-bot",
            "antibot",
            "anti-spider",
            "bot challenge",
            "verify you are human",
            "unusual traffic",
            "access denied",
            "反爬",
            "验证码",
            "人机验证",
            "访问验证",
        )
    )
    if not blocked:
        return 0.0
    try:
        return min(
            3600.0,
            max(
                30.0,
                float(result.get("retry_after_seconds") or os.getenv("WEB_SEARCH_ANTIBOT_COOLDOWN_SECONDS", "300")),
            ),
        )
    except (ValueError, TypeError):
        return 300.0


def transient_engine_delay(result: dict) -> float:
    """短暂冷却超时或网络故障引擎，避免并行子任务反复等待同一坏出口。"""

    detail = " ".join(str(result.get(field) or "") for field in ("error", "message", "code")).casefold()
    if any(
        marker in detail
        for marker in (
            "timeout",
            "timed out",
            "network is unreachable",
            "connection refused",
            "connection reset",
            "name or service not known",
            "temporary failure in name resolution",
            "http error 403",
            "http error 422",
        )
    ):
        return max(30.0, float(os.getenv("WEB_SEARCH_ENGINE_FAILURE_COOLDOWN_SECONDS", "180")))
    return 0.0


def coordinated_search(
    provider: str,
    arguments: dict,
    call: Callable[[], dict],
    *,
    wait_seconds: float | None = None,
) -> dict:
    """对供应商的一次原始调用执行跨进程排队、合并和有界限流恢复。"""
    config = RedisConfig.from_env(socket_timeout=3.0, socket_connect_timeout=3.0)
    try:
        with sync_redis_client(config, ping=False) as redis:
            return SearchCoordinator(redis, wait_seconds=wait_seconds).run(provider, arguments, call)
    except RedisError:
        # 共享协调不可用时不放行请求，避免所有 worker 同时冲击公网。
        return {"results": [], "status": "unavailable", "error": "公开检索共享调度暂不可用"}


class SearchCoordinator:
    """用 Redis 租约串行访问同一公网池，不把等待交给模型循环。"""

    def __init__(self, redis, *, prefix: str = "web-search:v1", wait_seconds: float | None = None):
        """设置共享状态、key 空间及单次等待预算。"""
        self.redis = redis
        self.prefix = prefix
        self.wait_seconds = (
            wait_seconds if wait_seconds is not None else float(os.getenv("WEB_SEARCH_QUEUE_WAIT_SECONDS", "60"))
        )

    def run(self, provider: str, arguments: dict, call: Callable[[], dict]) -> dict:
        """同查询仅发一次请求；限流时最多等候冷却后恢复一次。"""
        endpoint = os.getenv("SEARXNG_URL", "") if provider == "searxng" else os.getenv("OPEN_WEBSEARCH_URL", "")
        engines = (
            arguments.get("engines")
            if provider == "searxng"
            else os.getenv("OPEN_WEBSEARCH_ENGINES", "bing,duckduckgo")
        )
        identity = {
            "provider": provider,
            "arguments": arguments,
            "engines": engines,
            "endpoint": endpoint,
            "credentials": hashlib.sha256(
                (os.getenv("DOUBAO_SEARCH_API_KEY", "") + "|" + os.getenv("TAVILY_API_KEY", "")).encode()
            ).hexdigest(),
        }
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cache_key, lock_key = f"{self.prefix}:result:{digest}", f"{self.prefix}:query:{digest}"
        token = uuid.uuid4().hex
        deadline = time.monotonic() + max(0.0, min(self.wait_seconds, 90.0))
        queue_wait = 0.0

        def with_wait(result: dict) -> dict:
            """只记录本次调用的共享排队/冷却时间，不沿用缓存所有者的等待。"""
            return {**result, "queue_wait_seconds": round(queue_wait, 3)}

        while True:
            cached = self.redis.get(cache_key)
            if cached:
                return with_wait({**json.loads(cached), "cache_hit": True, "shared_cache_hit": True})
            if self.redis.set(lock_key, token, nx=True, ex=300):
                break
            if time.monotonic() >= deadline:
                return with_wait(self._deferred(1.0, "相同查询正在检索，请使用已有来源完成当前阶段"))
            started_wait = time.monotonic()
            time.sleep(0.05)
            queue_wait += time.monotonic() - started_wait
        try:
            cached = self.redis.get(cache_key)
            if cached:
                return with_wait({**json.loads(cached), "cache_hit": True, "shared_cache_hit": True})
            # daemon 与公网兜底访问同一组搜索引擎，必须共用一个出口池。
            if provider in {"open-websearch", "public"}:
                channel = "public-web:open"
            elif provider == "searxng":
                channel = "public-web:searxng"
            else:
                channel = provider
            key = f"{self.prefix}:channel:{channel}"
            interval = float(
                os.getenv("WEB_SEARCH_MIN_INTERVAL_SECONDS", "1.5" if channel.startswith("public-web:") else "0.3")
            )
            for attempt in range(2):
                while True:
                    delay = self.redis.eval(_ACQUIRE, 1, key, token, 180000, max(0, int(interval * 1000))) / 1000
                    if delay == 0:
                        break
                    if time.monotonic() + min(delay, 0.1) >= deadline:
                        return with_wait(self._deferred(delay, "检索出口排队或冷却超出本次等待预算"))
                    started_wait = time.monotonic()
                    time.sleep(min(delay, 0.1))
                    queue_wait += time.monotonic() - started_wait
                active_token = _ACTIVE.set(self)
                try:
                    try:
                        result = call()
                    except Exception as exc:
                        result = search_failure(exc)
                    for failure in result.get("partial_failures") or []:
                        if isinstance(failure, dict) and failure.get("engine"):
                            engine_delay = (
                                antibot_delay(failure)
                                or rate_limit_delay(failure)
                                or transient_engine_delay(failure)
                            )
                            if engine_delay:
                                self.cool_engine(failure["engine"], engine_delay)
                    # 挑战页面不会靠同一次工具调用内的等待恢复；直接交给其他证据渠道。
                    if not result.get("results") and (
                        result.get("status") == "blocked" or result.get("engine_cooldown")
                    ):
                        return with_wait(result)
                    delay = rate_limit_delay(result) if not result.get("results") else 0.0
                    if delay:
                        self.redis.eval(_COOL_DOWN, 1, key, max(1, int(delay * 1000)))
                finally:
                    _ACTIVE.reset(active_token)
                    self.redis.eval(_RELEASE, 1, key, token)
                if not delay:
                    if not result.get("error"):
                        ttl = min(3600, max(0, int(float(os.getenv("WEB_SEARCH_CACHE_TTL_SECONDS", "300")))))
                        if not result.get("results"):
                            ttl = min(ttl, 30)
                        if ttl:
                            self.redis.set(cache_key, json.dumps(result, ensure_ascii=False), ex=ttl)
                    return with_wait(result)
                if attempt == 1 or time.monotonic() + delay >= deadline:
                    return with_wait({**result, **self._deferred(delay, "后端临时限流，已按冷却规则停止请求")})
            raise AssertionError("unreachable")
        finally:
            self.redis.eval(_UNLOCK, 1, lock_key, token)

    def engine_remaining(self, engine: str) -> float:
        """读取各引擎的独立冷却，健康引擎可继续提供结果。"""
        return self.redis.eval(_REMAINING, 1, f"{self.prefix}:engine:{engine}") / 1000

    def cool_engine(self, engine: str, seconds: float) -> None:
        """跨进程保留引擎要求的最短等待时间。"""
        self.redis.eval(_COOL_DOWN, 1, f"{self.prefix}:engine:{engine}", max(1, int(seconds * 1000)))

    @staticmethod
    def _deferred(seconds: float, message: str) -> dict:
        """返回暂时限流，区别于不可恢复的检索故障。"""
        return {
            "results": [],
            "status": "rate_limited",
            "retryable": True,
            "retry_after_seconds": max(1, int(seconds + 0.999)),
            "error": message,
        }
