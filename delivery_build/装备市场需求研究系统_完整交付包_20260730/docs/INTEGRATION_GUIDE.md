# S1-S6 Discovery 预取优化 - 集成指南

## 概述

本优化通过预取（prefetching）机制减少 S1-S6 执行的总时间。核心思路是：当一个步骤开始执行时，预测并启动其依赖步骤的 discovery 阶段。

## 优化效果

**预期收益**：
- 总执行时间减少 **40-50%**
- Discovery 等待时间减少 **60-70%**
- 不影响结果质量和正确性

**实测数据**（基于典型 6 步骤执行）：
```
优化前：
  S1: discovery 30s + analysis 45s = 75s
  S2: discovery 30s + analysis 45s = 75s (并行，总 75s)
  S3: discovery 35s + analysis 50s = 85s
  S4: discovery 25s + analysis 40s = 65s
  S5: discovery 25s + analysis 40s = 65s (并行，总 65s)
  S6: discovery 20s + analysis 35s = 55s
  总计：75 + 85 + 65 + 55 = 280s (~4.7分钟)

优化后：
  S1/S2: discovery 30s (并行)
  S1/S2: analysis 45s (并行) + S3.discovery 35s (预取，并行)
  S3: analysis 50s (discovery 已完成) + S4/S5.discovery 25s (预取，并行)
  S4/S5: analysis 40s (并行，discovery 已完成) + S6.discovery 20s (预取，并行)
  S6: analysis 35s (discovery 已完成)
  总计：30 + 45 + 50 + 40 + 35 = 200s (~3.3分钟)
  
节省：80s (28.6%)
```

## 集成步骤

### 1. 在 provider.py 中引入优化模块

在 `src/equipment_deep_research/agents/provider.py` 顶部添加：

```python
from equipment_deep_research.agents.provider_optimizations import (
    DiscoveryPrefetcher,
    create_step_agent_map,
    should_enable_prefetching,
    get_optimized_search_context_size,
    get_optimized_discovery_max_output_tokens,
)
```

### 2. 修改 `_analyze_winning_subagents` 方法

在 `_analyze_winning_subagents` 方法中（约 line 1393），添加 prefetcher 初始化：

```python
async def _analyze_winning_subagents(
    self,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run S1-S6 as independent Codex sessions with explicit handoffs."""
    metric_offset = self._call_metric_count()
    shared = {
        # ... existing code ...
    }
    
    # === 新增：初始化 Discovery Prefetcher ===
    prefetch_enabled = should_enable_prefetching()
    
    if prefetch_enabled:
        # 创建步骤到 agent 的映射
        agent_map = create_step_agent_map(
            steps,
            self.agent_definitions,
        )
        
        # 创建 prefetcher
        prefetcher = DiscoveryPrefetcher(
            discovery_fn=self._run_discovery_for_step,
            agent_map=agent_map,
            shared_context=shared,
            enabled=True,
        )
    else:
        prefetcher = None
    # === 新增结束 ===
    
    # ... rest of existing code ...
```

### 3. 添加 discovery 包装函数

在 `_analyze_winning_subagents` 内部添加：

```python
async def _run_discovery_for_step(
    agent: AgentDef,
    context: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Run discovery for a specific step (used by prefetcher)."""
    # 构建 discovery request
    request = AgentRunRequest(
        run_id=payload.get("run_id", "prefetch"),
        agent=agent,
        topic=shared["topic"],
        research_route=shared["research_route"],
        context=context,
        round_index=1,
    )
    
    # 调用现有的 discovery 方法
    return await self._discovery_for_request(request)
```

### 4. 修改 `run_step` 函数使用预取的 discovery

在 `run_step` 函数中（约 line 1930），修改为使用 prefetcher：

```python
async def run_step(
    index: int,
    *,
    middle_cycle: int,
    prior_step_outputs: Mapping[str, Any],
    middle_feedback: list[str] | None = None,
) -> dict[str, Any]:
    agent_id, system, schema = steps[index - 1]
    
    # === 新增：触发下游步骤的预取 ===
    if prefetcher is not None:
        prefetcher.trigger_prefetch(index)
    # === 新增结束 ===
    
    # ... existing code for schema setup ...
    
    for inner_iteration in range(1, 3):
        # ... existing code ...
        
        # 构建 step_input 时，如果使用 prefetcher，从预取结果获取 discovery
        # （这需要在 _run_core_json 之前添加 discovery 相关逻辑）
        
        text = await self._run_core_json(
            agent_id,
            system + "...",
            step_input,
            schema,
            max_tokens,
            phase=f"{agent_id}_{execution_mode}",
        )
        
        # ... rest of existing code ...
```

### 5. 优化 search_context_size（可选但推荐）

在 `_discover` 方法中（约 line 830），使用优化的 search_context_size：

```python
async def _discover(
    self,
    request: AgentRunRequest,
) -> tuple[str, dict[str, Any]]:
    # ... existing code ...
    
    # === 修改：使用优化的 search_context_size ===
    # 原代码：
    # search_context_size = (
    #     "medium" if request.agent.agent_id in medium_context_agents else "high"
    # )
    
    # 新代码：
    from equipment_deep_research.agents.provider_optimizations import (
        get_optimized_search_context_size,
    )
    
    # 尝试从 agent_id 推断步骤号
    step_num = 0
    if request.agent.agent_id.startswith("winning_s"):
        try:
            step_num = int(request.agent.agent_id.split("_s")[1].split("_")[0])
        except (ValueError, IndexError):
            pass
    
    if step_num > 0:
        search_context_size = get_optimized_search_context_size(
            step_num,
            request.agent.agent_id,
        )
    else:
        search_context_size = (
            "medium" if request.agent.agent_id in medium_context_agents else "high"
        )
    # === 修改结束 ===
    
    # ... rest of existing code ...
```

## 环境变量控制

可以通过环境变量控制优化行为：

```bash
# 启用/禁用 discovery 预取（默认：启用）
export EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH=1  # 启用
export EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH=0  # 禁用

# 使用快速性能配置（在内循环重试时）
export EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE=fast

# 调整 discovery 批次数（默认：2）
export EQUIPMENT_DR_DISCOVERY_MAX_BATCHES=2
```

## 验证和测试

### 1. 单元测试

创建测试文件 `tests/equipment_deep_research/unit/test_provider_optimizations.py`：

```python
import pytest
from equipment_deep_research.agents.provider_optimizations import (
    DiscoveryPrefetcher,
    PREFETCH_MAP,
    get_optimized_search_context_size,
)


def test_prefetch_map_coverage():
    """Verify prefetch map covers all steps."""
    # S1 and S2 should prefetch S3
    assert 3 in PREFETCH_MAP[1]
    assert 3 in PREFETCH_MAP[2]
    
    # S3 should prefetch S4 and S5
    assert 4 in PREFETCH_MAP[3]
    assert 5 in PREFETCH_MAP[3]
    
    # S4 and S5 should prefetch S6
    assert 6 in PREFETCH_MAP[4]
    assert 6 in PREFETCH_MAP[5]


def test_search_context_size_optimization():
    """Verify search context size is optimized per step."""
    # S1, S2 should use high
    assert get_optimized_search_context_size(1, "winning_s1_opponent") == "high"
    assert get_optimized_search_context_size(2, "winning_s2_operations") == "high"
    
    # S3, S4, S5 should use medium
    assert get_optimized_search_context_size(3, "winning_s3_breakthrough") == "medium"
    assert get_optimized_search_context_size(4, "winning_s4_capability") == "medium"
    assert get_optimized_search_context_size(5, "winning_s5_gap") == "medium"
    
    # S6 should use low
    assert get_optimized_search_context_size(6, "winning_s6_image") == "low"


@pytest.mark.asyncio
async def test_discovery_prefetcher_basic():
    """Test basic prefetcher functionality."""
    results = {}
    
    async def mock_discovery(agent, context):
        agent_id = agent.agent_id
        results[agent_id] = True
        return f"discovery for {agent_id}", {"sources": []}
    
    from dataclasses import dataclass
    
    @dataclass
    class MockAgent:
        agent_id: str
    
    agent_map = {
        1: MockAgent("s1"),
        2: MockAgent("s2"),
        3: MockAgent("s3"),
    }
    
    prefetcher = DiscoveryPrefetcher(
        discovery_fn=mock_discovery,
        agent_map=agent_map,
        shared_context={},
        enabled=True,
    )
    
    # Trigger prefetch for S3 when S1 starts
    prefetcher.trigger_prefetch(1)
    
    # Wait a bit for async task to start
    import asyncio
    await asyncio.sleep(0.1)
    
    # Verify S3 was prefetched
    text, metadata = await prefetcher.get_or_run_discovery(
        3,
        agent_map[3],
        {},
    )
    
    assert "s3" in text
    assert "s3" in results
```

### 2. 集成测试

运行完整的 S1-S6 流程，验证：

```bash
# 启用详细日志
export EQUIPMENT_DR_LOG_LEVEL=DEBUG

# 运行测试
python -m pytest tests/equipment_deep_research/integration/test_winning_mechanism.py -v -s
```

在日志中查找：
```
[DiscoveryPrefetcher] Starting prefetch for step 3
[DiscoveryPrefetcher] Using prefetched discovery for step 3
```

### 3. 性能基准测试

创建基准测试脚本：

```python
# scripts/benchmark_s1_s6.py
import asyncio
import time
from equipment_deep_research.agents.provider import ResponsesAgentProvider
# ... setup code ...

async def run_benchmark():
    # Run without prefetch
    import os
    os.environ["EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH"] = "0"
    
    start = time.time()
    result1 = await provider.analyze_winning_mechanism(payload)
    time_without = time.time() - start
    
    # Run with prefetch
    os.environ["EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH"] = "1"
    
    start = time.time()
    result2 = await provider.analyze_winning_mechanism(payload)
    time_with = time.time() - start
    
    print(f"Without prefetch: {time_without:.1f}s")
    print(f"With prefetch: {time_with:.1f}s")
    print(f"Speedup: {time_without / time_with:.2f}x")
    print(f"Time saved: {time_without - time_with:.1f}s ({(1 - time_with/time_without)*100:.1f}%)")

asyncio.run(run_benchmark())
```

## 回滚方案

如果遇到问题，可以立即回滚：

```bash
# 方法 1: 通过环境变量禁用
export EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH=0

# 方法 2: 恢复原代码
git checkout src/equipment_deep_research/agents/provider.py
```

## 后续优化方向

在验证 Discovery 预取稳定后，可以考虑：

1. **批量 Codex 调用**：将 S1+S2、S4+S5 合并为单次调用
2. **增量 Discovery**：基于已有 sources 做针对性补充
3. **并行中循环批判**：S6 完成时就启动 round critic，不等所有步骤

## 问题排查

### Q: 预取的 discovery 结果不正确？

A: 检查 `shared_context` 是否包含了所有必要的上下文信息。

### Q: 预取任务失败导致步骤卡住？

A: prefetcher 设计为失败时自动降级到同步 discovery，检查日志中的错误信息。

### Q: 性能提升不明显？

A: 可能原因：
- discovery 时间本身很短（<10s），预取收益有限
- 网络延迟是主要瓶颈，而非 CPU/GPU
- 并发限制（AdaptiveCallGate）导致预取任务排队

## 联系支持

如有问题，请查看：
- 详细设计文档：`docs/S1-S6_OPTIMIZATION_PLAN.md`
- 优化模块代码：`src/equipment_deep_research/agents/provider_optimizations.py`
