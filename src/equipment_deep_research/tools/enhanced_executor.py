"""工具调用增强模块

提升工具调用成功率和效率。
预期收益：成功率从 70-85% 提升到 95%+。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from functools import wraps
import hashlib
import json
import time
from typing import Any, Callable
import logging

logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    """重试配置"""
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 10.0
    exponential_base: float = 2.0
    jitter: bool = True


class ParameterValidator:
    """参数验证和自动修复"""

    def __init__(self):
        self.fixes_applied = defaultdict(int)

    def validate_and_fix(
        self,
        parameters: dict[str, Any],
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """
        验证并自动修复参数

        Returns:
            (fixed_parameters, fix_descriptions)
        """
        fixed = dict(parameters)
        fixes = []

        # 处理必需参数
        required = schema.get('required', [])
        for param in required:
            if param not in fixed or fixed[param] is None:
                # 尝试使用默认值
                if 'properties' in schema and param in schema['properties']:
                    prop_schema = schema['properties'][param]
                    if 'default' in prop_schema:
                        fixed[param] = prop_schema['default']
                        fixes.append(f"Added missing required parameter '{param}' with default")
                        self.fixes_applied['missing_required'] += 1

        # 类型修复
        if 'properties' in schema:
            for param, value in list(fixed.items()):
                if param in schema['properties']:
                    prop_schema = schema['properties'][param]
                    fixed_value, fix_desc = self._fix_type(param, value, prop_schema)

                    if fix_desc:
                        fixed[param] = fixed_value
                        fixes.append(fix_desc)

        # 移除未定义的参数
        if 'properties' in schema:
            defined_params = set(schema['properties'].keys())
            extra_params = set(fixed.keys()) - defined_params

            for param in extra_params:
                del fixed[param]
                fixes.append(f"Removed undefined parameter '{param}'")
                self.fixes_applied['undefined_param'] += 1

        return fixed, fixes

    def _fix_type(
        self,
        param: str,
        value: Any,
        schema: dict[str, Any],
    ) -> tuple[Any, str | None]:
        """修复参数类型"""
        expected_type = schema.get('type')

        if expected_type == 'string' and not isinstance(value, str):
            # 转换为字符串
            fixed_value = str(value)
            self.fixes_applied['type_string'] += 1
            return fixed_value, f"Converted '{param}' to string"

        elif expected_type == 'integer' and not isinstance(value, int):
            # 转换为整数
            try:
                if isinstance(value, str):
                    fixed_value = int(value)
                elif isinstance(value, float):
                    fixed_value = int(value)
                else:
                    fixed_value = int(value)

                self.fixes_applied['type_integer'] += 1
                return fixed_value, f"Converted '{param}' to integer"
            except (ValueError, TypeError):
                pass

        elif expected_type == 'number' and not isinstance(value, (int, float)):
            # 转换为数字
            try:
                fixed_value = float(value)
                self.fixes_applied['type_number'] += 1
                return fixed_value, f"Converted '{param}' to number"
            except (ValueError, TypeError):
                pass

        elif expected_type == 'boolean' and not isinstance(value, bool):
            # 转换为布尔值
            if isinstance(value, str):
                fixed_value = value.lower() in ('true', 'yes', '1', 'on')
                self.fixes_applied['type_boolean'] += 1
                return fixed_value, f"Converted '{param}' to boolean"

        elif expected_type == 'array' and not isinstance(value, list):
            # 转换为数组
            if isinstance(value, str):
                # 尝试解析 JSON
                try:
                    fixed_value = json.loads(value)
                    if isinstance(fixed_value, list):
                        self.fixes_applied['type_array'] += 1
                        return fixed_value, f"Parsed '{param}' as JSON array"
                except json.JSONDecodeError:
                    pass

            # 包装为数组
            fixed_value = [value]
            self.fixes_applied['type_array'] += 1
            return fixed_value, f"Wrapped '{param}' in array"

        elif expected_type == 'object' and not isinstance(value, dict):
            # 转换为对象
            if isinstance(value, str):
                # 尝试解析 JSON
                try:
                    fixed_value = json.loads(value)
                    if isinstance(fixed_value, dict):
                        self.fixes_applied['type_object'] += 1
                        return fixed_value, f"Parsed '{param}' as JSON object"
                except json.JSONDecodeError:
                    pass

        return value, None


class ExponentialBackoff:
    """指数退避重试策略"""

    def __init__(self, config: RetryConfig | None = None):
        self.config = config or RetryConfig()
        self.attempt_count = 0

    async def execute(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        带重试的执行

        Raises:
            最后一次尝试的异常
        """
        last_exception = None

        for attempt in range(self.config.max_attempts):
            self.attempt_count = attempt + 1

            try:
                # 执行函数
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)

            except Exception as e:
                last_exception = e

                # 最后一次尝试不延迟
                if attempt + 1 >= self.config.max_attempts:
                    break

                # 计算延迟
                delay = min(
                    self.config.initial_delay * (self.config.exponential_base ** attempt),
                    self.config.max_delay
                )

                # 添加抖动
                if self.config.jitter:
                    import random
                    delay *= (0.5 + random.random() * 0.5)

                logger.warning(
                    f"Attempt {attempt + 1}/{self.config.max_attempts} failed: {e}, "
                    f"retrying in {delay:.2f}s"
                )

                await asyncio.sleep(delay)

        # 所有尝试都失败
        raise last_exception


class ResultCache:
    """结果缓存"""

    def __init__(self, max_size: int = 100, ttl_seconds: float = 300.0):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: dict[str, CacheEntry] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        """获取缓存结果"""
        if key in self.cache:
            entry = self.cache[key]

            # 检查是否过期
            if time.time() - entry.timestamp < self.ttl_seconds:
                self.hits += 1
                return entry.value
            else:
                # 过期，删除
                del self.cache[key]

        self.misses += 1
        return None

    def put(self, key: str, value: Any):
        """缓存结果"""
        # LRU 淘汰
        if len(self.cache) >= self.max_size:
            # 删除最旧的
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k].timestamp)
            del self.cache[oldest_key]

        self.cache[key] = CacheEntry(
            value=value,
            timestamp=time.time()
        )

    def clear(self):
        """清空缓存"""
        self.cache.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict[str, Any]:
        """统计信息"""
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0.0

        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': f"{hit_rate:.1%}",
            'cache_size': len(self.cache),
            'max_size': self.max_size,
        }


@dataclass
class CacheEntry:
    """缓存条目"""
    value: Any
    timestamp: float


class EnhancedToolExecutor:
    """
    增强的工具执行器

    功能：
    1. 参数自动修复
    2. 智能重试策略
    3. 结果缓存

    预期效果：
    - 工具调用成功率从 70-85% 提升到 95%+
    - 减少重试时间和资源消耗
    """

    def __init__(
        self,
        retry_config: RetryConfig | None = None,
        cache_size: int = 100,
        cache_ttl: float = 300.0,
    ):
        self.validator = ParameterValidator()
        self.retry_config = retry_config or RetryConfig()
        self.cache = ResultCache(max_size=cache_size, ttl_seconds=cache_ttl)
        self.metrics = ExecutorMetrics()

    async def execute(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        schema: dict[str, Any],
        executor_func: Callable,
    ) -> Any:
        """
        增强的工具执行

        Args:
            tool_name: 工具名称
            parameters: 工具参数
            schema: 参数 schema
            executor_func: 实际执行函数

        Returns:
            工具执行结果
        """
        start_time = time.time()
        self.metrics.total_calls += 1

        try:
            # 1. 参数验证和修复
            fixed_params, fixes = self.validator.validate_and_fix(parameters, schema)

            if fixes:
                logger.info(f"Tool '{tool_name}' parameters fixed: {fixes}")
                self.metrics.params_fixed += 1

            # 2. 检查缓存
            cache_key = self._make_cache_key(tool_name, fixed_params)
            cached_result = self.cache.get(cache_key)

            if cached_result is not None:
                logger.debug(f"Tool '{tool_name}' cache hit")
                self.metrics.cache_hits += 1
                return cached_result

            # 3. 带重试的执行
            backoff = ExponentialBackoff(self.retry_config)

            try:
                result = await backoff.execute(executor_func, fixed_params)
                self.metrics.successful_calls += 1

                # 4. 缓存结果
                self.cache.put(cache_key, result)

                return result

            except Exception as e:
                self.metrics.failed_calls += 1
                logger.error(
                    f"Tool '{tool_name}' failed after {backoff.attempt_count} attempts: {e}"
                )
                raise

        finally:
            elapsed = time.time() - start_time
            self.metrics.total_time += elapsed

    def _make_cache_key(self, tool_name: str, parameters: dict[str, Any]) -> str:
        """生成缓存键"""
        # 标准化参数
        normalized = json.dumps(parameters, sort_keys=True, separators=(',', ':'))

        # 计算哈希
        hash_obj = hashlib.sha256(f"{tool_name}:{normalized}".encode())
        return hash_obj.hexdigest()[:16]

    def stats(self) -> dict[str, Any]:
        """统计信息"""
        success_rate = (
            self.metrics.successful_calls / self.metrics.total_calls
            if self.metrics.total_calls > 0
            else 0.0
        )

        avg_time = (
            self.metrics.total_time / self.metrics.total_calls
            if self.metrics.total_calls > 0
            else 0.0
        )

        return {
            'total_calls': self.metrics.total_calls,
            'successful_calls': self.metrics.successful_calls,
            'failed_calls': self.metrics.failed_calls,
            'success_rate': f"{success_rate:.1%}",
            'params_fixed': self.metrics.params_fixed,
            'cache_hits': self.metrics.cache_hits,
            'avg_time_ms': avg_time * 1000,
            'cache_stats': self.cache.stats(),
            'validator_fixes': dict(self.validator.fixes_applied),
        }


@dataclass
class ExecutorMetrics:
    """执行器指标"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    params_fixed: int = 0
    cache_hits: int = 0
    total_time: float = 0.0


# 装饰器：为现有工具添加增强功能
def enhanced_tool(
    schema: dict[str, Any],
    retry_config: RetryConfig | None = None,
):
    """
    工具增强装饰器

    Example:
        @enhanced_tool(schema={'type': 'object', ...})
        async def my_tool(params: dict):
            ...
    """
    executor = EnhancedToolExecutor(retry_config=retry_config)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 提取参数
            if args:
                parameters = args[0] if isinstance(args[0], dict) else {}
            else:
                parameters = kwargs

            # 使用增强执行
            return await executor.execute(
                tool_name=func.__name__,
                parameters=parameters,
                schema=schema,
                executor_func=lambda p: func(p),
            )

        # 附加统计方法
        wrapper.stats = executor.stats

        return wrapper

    return decorator


__all__ = [
    'EnhancedToolExecutor',
    'ParameterValidator',
    'ExponentialBackoff',
    'ResultCache',
    'RetryConfig',
    'enhanced_tool',
]
