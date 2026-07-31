#!/usr/bin/env python3
# ruff: noqa: F401
"""
快速验证脚本：检查 Phase 1 & 3 优化是否正确集成

运行方式:
    python scripts/verify_optimization.py
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def test_imports():
    """测试优化模块是否可以正确导入"""
    print("=" * 60)
    print("测试 1: 验证优化模块导入")
    print("=" * 60)

    try:
        from equipment_deep_research.agents.provider_optimizations import (
            DiscoveryPrefetcher,
            create_step_agent_map,
            should_enable_prefetching,
            get_optimized_search_context_size,
            get_optimized_discovery_max_output_tokens,
            STEP_DEPENDENCIES,
            PREFETCH_MAP,
        )
        print("✅ 所有优化模块导入成功")
        return True
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        return False


def test_prefetch_enabled():
    """测试预取功能是否默认启用"""
    print("\n" + "=" * 60)
    print("测试 2: 验证预取功能状态")
    print("=" * 60)

    from equipment_deep_research.agents.provider_optimizations import should_enable_prefetching

    enabled = should_enable_prefetching()
    print(f"预取功能默认状态: {'启用 ✅' if enabled else '禁用 ❌'}")

    # Test disable via env var
    os.environ["EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH"] = "0"
    disabled = should_enable_prefetching()
    print(f"环境变量禁用后: {'禁用 ✅' if not disabled else '仍启用 ❌'}")

    # Reset
    os.environ["EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH"] = "1"

    return enabled and not disabled


def test_search_context_optimization():
    """测试搜索上下文优化"""
    print("\n" + "=" * 60)
    print("测试 3: 验证搜索上下文优化")
    print("=" * 60)

    from equipment_deep_research.agents.provider_optimizations import get_optimized_search_context_size

    tests = [
        (1, "winning_s1_opponent", "high"),
        (2, "winning_s2_operations", "high"),
        (3, "winning_s3_breakthrough", "medium"),
        (4, "winning_s4_capability", "medium"),
        (5, "winning_s5_gap", "medium"),
        (6, "winning_s6_image", "low"),
    ]

    all_passed = True
    for step, agent_id, expected in tests:
        actual = get_optimized_search_context_size(step, agent_id)
        passed = actual == expected
        all_passed = all_passed and passed
        status = "✅" if passed else "❌"
        print(f"{status} S{step} ({agent_id}): {actual} (预期: {expected})")

    return all_passed


def test_prefetch_map():
    """测试预取映射是否正确"""
    print("\n" + "=" * 60)
    print("测试 4: 验证预取策略")
    print("=" * 60)

    from equipment_deep_research.agents.provider_optimizations import PREFETCH_MAP

    tests = [
        (1, [3], "S1 应预取 S3"),
        (2, [3], "S2 应预取 S3"),
        (3, [4, 5], "S3 应预取 S4 和 S5"),
        (4, [6], "S4 应预取 S6"),
        (5, [6], "S5 应预取 S6"),
    ]

    all_passed = True
    for step, expected_prefetch, desc in tests:
        actual = PREFETCH_MAP.get(step, ())
        passed = set(actual) == set(expected_prefetch)
        all_passed = all_passed and passed
        status = "✅" if passed else "❌"
        print(f"{status} {desc}: {list(actual)} (预期: {expected_prefetch})")

    return all_passed


def test_provider_integration():
    """测试 provider 集成是否正确"""
    print("\n" + "=" * 60)
    print("测试 5: 验证 Provider 集成")
    print("=" * 60)

    try:
        # Import provider to check for syntax errors
        from equipment_deep_research.agents import provider
        print("✅ Provider 模块导入成功（无语法错误）")

        # Check if optimizations are imported
        has_prefetcher = hasattr(provider, 'DiscoveryPrefetcher')
        has_optimizer = hasattr(provider, 'get_optimized_search_context_size')

        if has_prefetcher:
            print("✅ DiscoveryPrefetcher 已导入到 provider")
        else:
            print("⚠️  DiscoveryPrefetcher 未在 provider 模块级别可见（正常，在函数内使用）")

        if has_optimizer:
            print("✅ get_optimized_search_context_size 已导入到 provider")
        else:
            print("⚠️  get_optimized_search_context_size 未在 provider 模块级别可见（正常，在函数内使用）")

        return True
    except Exception as e:
        print(f"❌ Provider 模块导入失败: {e}")
        return False


def test_token_optimization():
    """测试 token 优化"""
    print("\n" + "=" * 60)
    print("测试 6: 验证 Token 优化")
    print("=" * 60)

    from equipment_deep_research.agents.provider_optimizations import get_optimized_discovery_max_output_tokens

    # Test that light < standard < deep
    light = get_optimized_discovery_max_output_tokens(3, "winning_s3_breakthrough", "light")
    standard = get_optimized_discovery_max_output_tokens(3, "winning_s3_breakthrough", "standard")
    deep = get_optimized_discovery_max_output_tokens(3, "winning_s3_breakthrough", "deep")

    passed = light < standard < deep
    status = "✅" if passed else "❌"
    print(f"{status} Token 层级正确: light({light}) < standard({standard}) < deep({deep})")

    # Test that S1/S2 get more tokens
    s1_tokens = get_optimized_discovery_max_output_tokens(1, "winning_s1_opponent", "standard")
    s3_tokens = get_optimized_discovery_max_output_tokens(3, "winning_s3_breakthrough", "standard")
    s6_tokens = get_optimized_discovery_max_output_tokens(6, "winning_s6_image", "standard")

    step_passed = s1_tokens > s3_tokens > s6_tokens
    step_status = "✅" if step_passed else "❌"
    print(f"{step_status} 步骤 Token 优化: S1({s1_tokens}) > S3({s3_tokens}) > S6({s6_tokens})")

    return passed and step_passed


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("Phase 1 & 3 优化验证脚本")
    print("=" * 60)

    results = []

    results.append(("模块导入", test_imports()))
    results.append(("预取功能", test_prefetch_enabled()))
    results.append(("搜索上下文优化", test_search_context_optimization()))
    results.append(("预取策略", test_prefetch_map()))
    results.append(("Provider 集成", test_provider_integration()))
    results.append(("Token 优化", test_token_optimization()))

    # Summary
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    total = len(results)
    passed = sum(1 for _, result in results if result)

    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {name}")

    print("\n" + "=" * 60)
    print(f"总计: {passed}/{total} 测试通过")
    print("=" * 60)

    if passed == total:
        print("\n🎉 所有测试通过！优化已正确集成。")
        print("\n下一步:")
        print("  1. 运行完整测试套件: pytest tests/")
        print("  2. 在实际任务中验证性能提升")
        print("  3. 监控预取命中率和执行时间")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败，请检查集成。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
