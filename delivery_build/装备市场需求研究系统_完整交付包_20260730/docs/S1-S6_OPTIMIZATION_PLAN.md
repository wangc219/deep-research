# S1-S6 Agent (Codex CLI) 执行效率优化方案

## 问题诊断

### 当前瓶颈

1. **Discovery 阶段串行化**
   - 每个 S 步骤都需要先完成 web discovery，再进行 analysis
   - Discovery 阶段有独立的模型调用（search_context_size: high）
   - 当前机制：`_discovery_for_request` → `_discover` → 多个 lane 并行 → analysis

2. **未充分利用步骤间并行性**
   - S1 和 S2 完全独立，可以完全并行
   - S4 和 S5 都只依赖 S3，也可以完全并行
   - 但 discovery 阶段的串行化抵消了这些优势

3. **重复的 discovery 工作**
   - 虽然有 `_shared_discovery_sources`（line 1077-1136），但是后续步骤无法提前利用
   - 每个步骤都要等待自己的 discovery 完成

4. **模型调用未批量化**
   - 每个 S 步骤都是独立的 Codex CLI 进程调用
   - 进程启动和上下文切换开销大

## 优化方案

### 方案 1: Discovery 预取和流水线化（推荐）

**核心思路**：利用步骤依赖关系，在父步骤执行时预取子步骤的 discovery

```python
# 在 S1 运行时，同时启动 S3 的 discovery（因为 S3 需要等 S1+S2）
# 在 S3 运行时，同时启动 S4 和 S5 的 discovery
# 这样 S3 完成时，S4/S5 的 discovery 已经就绪

依赖图：
S1 ─┐
    ├─→ S3 ─┬─→ S4 ─┐
S2 ─┘       │       ├─→ S6
            └─→ S5 ─┘

优化后时间线：
Time 0:  S1.discovery + S2.discovery (并行)
Time 1:  S1.analysis  + S2.analysis  (并行) + S3.discovery (预取)
Time 2:  S3.analysis  + S4.discovery + S5.discovery (预取)
Time 3:  S4.analysis  + S5.analysis  (并行) + S6.discovery (预取)
Time 4:  S6.analysis

当前时间线：
Time 0:  S1.discovery + S2.discovery (并行)
Time 1:  S1.analysis  + S2.analysis  (并行)
Time 2:  S3.discovery
Time 3:  S3.analysis
Time 4:  S4.discovery + S5.discovery (并行)
Time 5:  S4.analysis  + S5.analysis  (并行)
Time 6:  S6.discovery
Time 7:  S6.analysis
```

**预期收益**：减少 40-50% 的总执行时间

### 方案 2: 批量 Codex 调用（中等复杂度）

**核心思路**：将多个独立的 S 步骤合并为一次 Codex 调用

```python
# 当前：S1, S2, S3, S4, S5, S6 各自启动独立的 Codex 进程
# 优化：S1+S2 合并，S4+S5 合并

# 优势：
# - 减少进程启动开销
# - 共享上下文加载
# - 减少网络往返

# 挑战：
# - 需要修改 structured output schema
# - 错误隔离变复杂
```

**预期收益**：减少 15-25% 的执行时间

### 方案 3: 增量 Discovery（长期方案）

**核心思路**：不是每个步骤都做全新 discovery，而是基于已有 sources 做增量搜索

```python
# S1: 完整 discovery (国际形势)
# S2: 完整 discovery (作战场景)
# S3: 增量 discovery (基于 S1+S2 的 sources，只补充缺失的维度)
# S4: 增量 discovery (基于 S1+S2+S3)
# ...

# 实现：
# 1. 每个步骤输出 "缺失的信息" 标签
# 2. 下一步骤根据标签做针对性搜索
# 3. 利用 incremental_knowledge 机制
```

**预期收益**：减少 30-40% 的 discovery 成本

## 实施优先级

### Phase 1: Discovery 预取（立即实施）✅
- 修改 `_analyze_winning_subagents` 添加预取逻辑
- 利用现有的 `_discovery_inflight` 机制
- 无需改变 API contract
- **风险低，收益高**

### Phase 2: 优化 Discovery 并发策略（1周内）
- 当前 `max_batches` 默认为 2
- 可以根据 agent 类型动态调整
- S1/S2 可以用更激进的并发策略

### Phase 3: 批量调用（2-3周）
- 需要谨慎设计错误处理
- 需要测试 Codex CLI 的 schema 复杂度上限

### Phase 4: 增量 Discovery（长期）
- 需要设计 "信息缺口" 的表示方法
- 需要验证增量搜索的质量

## 立即可执行的优化

### 1. 启用 Discovery 缓存的跨步骤复用

当前 `_shared_discovery_sources` 只在同一个 run_id 内的不同 agent 间共享，
但 S1-S6 应该能更充分利用这个机制。

### 2. 调整 search_context_size

```python
# 当前所有步骤都用 "high"
# 可以优化为：
S1, S2: "high"  # 需要广泛搜索
S3, S4, S5: "medium"  # 基于上游结论，范围更聚焦
S6: "low"  # 主要是综合，不需要新搜索
```

### 3. 启用 fast performance profile

```python
# 当前默认是 "quality"
# 可以在内循环重试时使用 "fast"
export EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE=fast
```

## 监控指标

需要跟踪以下指标来验证优化效果：

1. **总执行时间**
   - baseline → winning 的端到端时间
   - 目标：从当前 ~10-15分钟 降到 ~6-8分钟

2. **Discovery 时间占比**
   - 当前约占 60-70%
   - 目标：降到 40-50%

3. **并行度**
   - 同时运行的模型调用数
   - 目标：从平均 1.5 提升到 2.5

4. **Discovery 命中率**
   - 使用 shared sources 的比例
   - 目标：从 0% 提升到 30-40%
