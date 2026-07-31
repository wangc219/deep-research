# 动态调度器集成 - 下一步详细指令

**当前状态**: 已添加导入，准备集成核心逻辑

---

## 方式 1：我来帮你完成集成（推荐）⭐

我可以直接修改 `provider.py` 完成集成，你只需确认：

### 需要你确认的问题：

1. **是否允许我直接修改 `provider.py`？**
   - 文件位置：`src/equipment_deep_research/agents/provider.py`
   - 修改行数：约 200 行（2168-2391 行区域）
   - 改动内容：将固定波次调度替换为动态调度器
   - 向后兼容：通过环境变量 `EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER` 控制

2. **默认启用还是默认关闭？**
   - 选项 A：默认启用（`EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER=1`）
   - 选项 B：默认关闭（`EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER=0`），手动启用测试

### 如果你同意，我将执行：

```bash
# 1. 备份当前代码（自动）
# 2. 修改 provider.py 集成动态调度器
# 3. 运行验证脚本确认无语法错误
# 4. 给出测试命令
```

---

## 方式 2：你自己手动集成

如果你希望自己控制修改过程，按照以下步骤：

### 步骤 1：定位修改位置

```bash
cd "/Users/wangchen/equipment research"
```

打开 `src/equipment_deep_research/agents/provider.py`，找到第 **2197 行**：
```python
await run_step_waves(active_steps, middle_cycle=1)
```

### 步骤 2：替换执行逻辑

**原代码**（2168-2391 行）：
```python
async def run_step_waves(...):
    ...

await run_step_waves(active_steps, middle_cycle=1)

# 中循环批判
round_review_text = await self._run_core_json(...)
```

**替换为**：

参考 `docs/OPTIMIZATION_PLAN_A_IMPLEMENTATION.md` 第 67-165 行的完整代码。

关键改动：
1. 添加 `use_dynamic_scheduler` 开关
2. 定义 `middle_loop_critic` 函数
3. 定义 `run_step_for_scheduler` 适配器
4. 调用 `execute_s1_s6_dynamic`
5. 保留原有逻辑作为 `else` 分支

### 步骤 3：增强 schema（可选）

找到 **1937 行**附近的 `reasoning_node` schema，添加：
```python
"next_action": {
    "action": "continue|parallel|backtrack|recall|stop",
    "target_step": "1..6 or 0",
    "reason": "string",
    "affected_fields": ["string"],  # 新增此行
}
```

### 步骤 4：测试

```bash
# 语法检查
python3 -c "import equipment_deep_research.agents.provider"

# 烟雾测试
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "测试" \
  --research-route traditional_gap \
  --run-id integration-test
```

---

## 方式 3：渐进式集成（最保险）

如果担心一次性改动太大，可以分步集成：

### 阶段 1：只启用流水线并行（不改中循环）

```python
# 在 2197 行之前添加
use_dynamic_scheduler = os.environ.get(
    "EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER", "0"
).strip() == "1"

if use_dynamic_scheduler:
    # 简化版：只替换 run_step_waves，不改中循环
    from equipment_deep_research.orchestration.dynamic_winning_scheduler import (
        DynamicWinningScheduler,
    )
    
    scheduler = DynamicWinningScheduler(
        step_definitions=steps,
        step_modes=step_modes,
        run_step_fn=lambda s, c, _, f: run_step(s, c, dict(accumulated), f),
        commit_step_fn=commit_step,
        emit_progress_fn=self._emit_winning_progress,
    )
    
    await scheduler.execute_pipeline(middle_cycle=1)
else:
    # 原有逻辑
    await run_step_waves(active_steps, middle_cycle=1)

# 保持原有的中循环批判逻辑不变
round_review_text = await self._run_core_json(...)
```

测试通过后，再集成智能回溯。

### 阶段 2：启用智能回溯

参考完整实施指南添加 `middle_loop_critic` 和 `execute_s1_s6_dynamic`。

---

## 快速决策建议

### 如果你想快速验证效果：
→ **选择方式 1**，我来直接集成，5 分钟完成

### 如果你想完全掌控代码：
→ **选择方式 2**，手动集成，参考实施指南

### 如果你担心风险：
→ **选择方式 3**，渐进式集成，先测流水线，再加回溯

---

## 我的建议 ⭐

**推荐方式 1**，理由：
1. ✅ 核心逻辑已验证（validation script 通过）
2. ✅ 向后兼容（环境变量控制）
3. ✅ 可快速回滚（改环境变量即可）
4. ✅ 我可以确保语法正确、逻辑完整

你只需要回复：**"同意集成"** 或 **"我自己来"**，我会立即执行相应操作。

---

## 集成后的测试计划

无论选择哪种方式，集成后执行：

```bash
# 1. 验证语法
python3 -c "from equipment_deep_research.agents.provider import ResponsesAgentProvider"

# 2. 烟雾测试（fake 模式）
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人体系装备能力缺口" \
  --research-route traditional_gap \
  --run-id dynamic-smoke

# 3. 检查输出
cat "outputs/runs/dynamic-smoke/trace.jsonl" | grep "winning_" | head -20

# 4. 验证动态调度器是否生效
cat "outputs/runs/dynamic-smoke/round_summary.json" | jq '.backtrack_history'

# 5. 性能对比测试（可选）
# 关闭动态调度器
export EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER=0
python3 scripts/run_deep_research.py --mode real --run-id baseline

# 启用动态调度器
export EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER=1
python3 scripts/run_deep_research.py --mode real --run-id optimized
```

---

## 需要帮助？

- 集成过程遇到问题：检查 Python 语法错误信息
- 运行时错误：查看 `outputs/runs/*/trace.jsonl` 最后几行
- 性能不符合预期：提供 trace.jsonl，我帮你分析
- 想回滚：`export EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER=0`

等待你的指令！👍
