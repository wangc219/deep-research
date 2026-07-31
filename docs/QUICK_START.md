# S1-S6 优化 - 快速开始指南

## 🎯 目标

将 S1-S6 制胜机理分析的执行时间从 **~4.7分钟** 降到 **~3.3分钟**（节省 **28.6%**）

## 🚀 立即使用

### 方式 1: 仅启用优化（推荐用于测试）

优化模块已完成并测试通过，但尚未集成到生产代码中。你可以：

```bash
# 1. 查看优化模块
cat src/equipment_deep_research/agents/provider_optimizations.py

# 2. 运行单元测试验证
python -m pytest tests/equipment_deep_research/unit/test_provider_optimizations.py -v

# 预期结果: 13 passed ✅
```

### 方式 2: 集成到生产代码

**需要修改的文件**: `src/equipment_deep_research/agents/provider.py`

**修改点 1**: 引入模块（在文件顶部）

```python
from equipment_deep_research.agents.provider_optimizations import (
    DiscoveryPrefetcher,
    create_step_agent_map,
    should_enable_prefetching,
)
```

**修改点 2**: 在 `_analyze_winning_subagents` 方法中初始化 prefetcher（约 line 1393）

在 `shared = {...}` 定义之后添加：

```python
# 初始化 Discovery Prefetcher
if should_enable_prefetching() and self.provider_kind == "codex_cli":
    agent_map = create_step_agent_map(steps, self.agent_definitions)
    prefetcher = DiscoveryPrefetcher(
        discovery_fn=lambda agent, ctx: self._discovery_for_request(
            AgentRunRequest(
                run_id=shared.get("run_id", "prefetch"),
                agent=agent,
                topic=shared["topic"],
                research_route=shared["research_route"],
                context=ctx,
                round_index=1,
            )
        ),
        agent_map=agent_map,
        shared_context=shared,
        enabled=True,
    )
else:
    prefetcher = None
```

**修改点 3**: 在 `run_step` 函数开始处触发预取（约 line 1930）

在 `agent_id, system, schema = steps[index - 1]` 之后添加：

```python
# 触发下游步骤的预取
if prefetcher is not None:
    prefetcher.trigger_prefetch(index)
```

**就这么简单！** 3 个修改点，总共 ~20 行代码。

## 📊 验证效果

### 运行基准测试

创建脚本 `scripts/benchmark_prefetch.py`:

```python
import asyncio
import time
import os

async def benchmark():
    # 禁用预取运行
    os.environ["EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH"] = "0"
    # ... 运行 S1-S6 ...
    time_without = time.time() - start
    
    # 启用预取运行
    os.environ["EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH"] = "1"
    # ... 运行 S1-S6 ...
    time_with = time.time() - start
    
    print(f"不使用预取: {time_without:.1f}s")
    print(f"使用预取: {time_with:.1f}s")
    print(f"提速: {time_without / time_with:.2f}x")
    print(f"节省: {time_without - time_with:.1f}s")

asyncio.run(benchmark())
```

### 查看预取日志

在运行时，你会看到类似的日志：

```
[DiscoveryPrefetcher] Starting prefetch for step 3
[DiscoveryPrefetcher] Using prefetched discovery for step 3
[DiscoveryPrefetcher] Starting prefetch for step 4
[DiscoveryPrefetcher] Starting prefetch for step 5
[DiscoveryPrefetcher] Using prefetched discovery for step 4
[DiscoveryPrefetcher] Using prefetched discovery for step 5
[DiscoveryPrefetcher] Starting prefetch for step 6
[DiscoveryPrefetcher] Using prefetched discovery for step 6
```

## 🎛️ 配置选项

### 启用/禁用预取

```bash
# 启用（默认）
export EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH=1

# 禁用（回滚）
export EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH=0
```

### 其他优化配置

```bash
# 使用优化的 search_context_size
# S1/S2: high, S3/S4/S5: medium, S6: low
# (需要在 _discover 方法中集成)

# 快速模式（用于 light 执行模式）
export EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE=fast

# 减少 discovery 批次（加快速度，可能降低质量）
export EQUIPMENT_DR_DISCOVERY_MAX_BATCHES=1
```

## 🐛 问题排查

### Q: 看不到预取日志？

A: 确保：
1. 环境变量 `EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH=1`
2. `provider_kind == "codex_cli"`（不是 responses）
3. 在 `run_step` 中调用了 `prefetcher.trigger_prefetch(index)`

### Q: 性能没有提升？

A: 可能原因：
1. Discovery 本身很快（<10s），预取收益有限
2. 网络延迟是主要瓶颈
3. 并发限制（AdaptiveCallGate）导致预取任务排队

解决方案：
- 检查 discovery 实际耗时：`grep "baseline_discovery_completed" logs/`
- 调整并发限制：修改 `AdaptiveCallGate` 配置
- 使用 `EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE=fast`

### Q: 预取失败？

A: prefetcher 会自动降级到同步 discovery，不影响正确性。检查日志：

```bash
grep "Prefetch failed" logs/
```

## 📈 预期收益

| 场景 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 典型 6 步骤 | 280s | 200s | **28.6%** |
| Discovery 占比高 | 400s | 250s | **37.5%** |
| Discovery 占比低 | 200s | 170s | **15.0%** |

**实际收益取决于**：
- Discovery 阶段耗时占比
- 网络延迟
- 模型响应速度
- 并发限制配置

## 🔄 回滚方案

### 方法 1: 环境变量禁用（立即生效）

```bash
export EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH=0
```

### 方法 2: Git 回滚（移除集成代码）

```bash
git checkout src/equipment_deep_research/agents/provider.py
```

### 方法 3: 条件编译（保留代码，禁用功能）

在 `_analyze_winning_subagents` 中：

```python
if False:  # 临时禁用
    # prefetcher 初始化代码
    pass
else:
    prefetcher = None
```

## 📚 更多信息

- **详细原理**: `docs/S1-S6_OPTIMIZATION_PLAN.md`
- **集成指南**: `docs/INTEGRATION_GUIDE.md`
- **完成报告**: `docs/OPTIMIZATION_COMPLETION_REPORT.md`
- **源代码**: `src/equipment_deep_research/agents/provider_optimizations.py`
- **测试代码**: `tests/equipment_deep_research/unit/test_provider_optimizations.py`

## ✅ 检查清单

使用前请确认：

- [ ] 单元测试通过（13/13）
- [ ] 理解优化原理（Discovery 预取）
- [ ] 知道如何启用/禁用
- [ ] 知道如何查看效果
- [ ] 知道如何回滚

集成后请确认：

- [ ] 修改了 3 个代码点
- [ ] 运行集成测试
- [ ] 查看预取日志
- [ ] 对比性能数据
- [ ] 验证结果一致性

## 🎉 开始使用

```bash
# 1. 运行单元测试
pytest tests/equipment_deep_research/unit/test_provider_optimizations.py -v

# 2. 启用优化
export EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH=1

# 3. 运行你的 S1-S6 任务
python scripts/run_deep_research.py --topic "你的研究主题"

# 4. 观察日志中的预取信息
tail -f logs/research.log | grep "DiscoveryPrefetcher"
```

---

**需要帮助？** 查看文档或在项目 issue 中提问。
