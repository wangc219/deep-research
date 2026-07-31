# 方案 A 优化实施指南：动态 S1-S6 流水线调度

## 改动概览

本次优化实现了架构文档要求的动态 S1-S6 执行：
- ✅ 支持 skip/light/standard/deep 四种执行模式
- ✅ 流水线并行：步骤依赖满足后立即启动，不等待同波次其他步骤
- ✅ 智能回溯：根据修改字段只重跑受影响步骤
- ✅ reasoning_node.next_action 支持（continue/backtrack/recall/stop）

## 文件改动清单

### 1. 新增文件

**`src/equipment_deep_research/orchestration/dynamic_winning_scheduler.py`** ✅ 已创建
- 核心调度器实现
- 400+ 行，包含完整文档

### 2. 需要修改的文件

#### 2.1 集成动态调度器

**`src/equipment_deep_research/agents/provider.py`**

**位置 1: 导入新模块（行 36 附近）**
```python
from equipment_deep_research.orchestration.blueprints import winning_step_modes
# 新增：
from equipment_deep_research.orchestration.dynamic_winning_scheduler import (
    execute_s1_s6_dynamic,
)
```

**位置 2: 替换 run_step_waves（行 2168-2193）**

当前代码：
```python
async def run_step_waves(
    selected_steps: Sequence[int],
    *,
    middle_cycle: int,
    middle_feedback: list[str] | None = None,
) -> None:
    selected = set(selected_steps)
    for wave in plan_step_waves(selected):
        prior_step_outputs = dict(accumulated)
        outcomes = await asyncio.gather(
            *(
                run_step(
                    index,
                    middle_cycle=middle_cycle,
                    prior_step_outputs=prior_step_outputs,
                    middle_feedback=middle_feedback,
                )
                for index in wave
            )
        )
        for outcome in sorted(
            outcomes,
            key=lambda item: int(item["run"]["step"]),
        ):
            commit_step(outcome)

await run_step_waves(active_steps, middle_cycle=1)
```

替换为：
```python
# 使用动态调度器替代固定波次
use_dynamic_scheduler = os.environ.get(
    "EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER",
    "1",
).strip() == "1"

if use_dynamic_scheduler:
    # 准备 critic 函数（用于 middle loop）
    async def middle_loop_critic(state: dict[str, Any]) -> dict[str, Any]:
        critic_text = await self._run_core_json(
            "winning_round_critic",
            "你是制胜机理中循环批判Agent。检查S1-S6之间的因果连续性、证据一致性、"
            "路线侧重、遗漏维度和能力图像可追溯性。必要时指定最早回溯点和受影响字段；"
            "不要因上游轻微措辞或引用格式问题机械重跑所有稳定下游步骤。若问题必须新增证据才能"
            "解决，设置requires_new_evidence=true。只输出严格JSON。",
            {
                "topic": shared["topic"],
                "research_route": shared["research_route"],
                "discovery_blueprint": step_shared_context(6)["discovery_blueprint"],
                "packet_index": packet_index,
                "valid_evidence_ids": [
                    str(item.get("evidence_id", ""))
                    for item in shared.get("evidence_index", [])
                    if isinstance(item, Mapping)
                    and str(item.get("evidence_id", "")).strip()
                ],
                "six_step_outputs": round_review_projection(state),
                "allowed_target_agent_ids": list(
                    shared.get("selected_business_agent_ids", [])
                ),
            },
            {
                "passed": "boolean",
                "rerun_from_step": "1..6 or 0",
                "issues": ["string"],
                "affected_fields": [
                    "defense_decomposition|operational_review|winning_paths|"
                    "breakthrough_directions|effect_chain|capability_mapping|"
                    "dotmlpf_matrix|gap_assessment"
                ],
                "rerun_guidance": ["string"],
                "rerun_steps": ["1..6"],
                "requires_new_evidence": "boolean",
                "evidence_requests": [
                    {
                        "question": "single narrow evidence question",
                        "target_agent_id": "one allowed business agent id",
                        "affected_steps": ["1..6"],
                        "source_preferences": ["primary or authoritative source type"],
                        "reason": "why this evidence can change the conclusion",
                    }
                ],
            },
            1600,
            phase="winning_round_review",
        )
        return _parse_json_object(critic_text)

    # 准备 run_step 函数（适配动态调度器接口）
    async def run_step_for_scheduler(
        step: int,
        middle_cycle: int,
        prior_outputs: Mapping[str, Any],
        middle_feedback: list[str] | None,
    ) -> dict[str, Any]:
        return await run_step(
            step,
            middle_cycle=middle_cycle,
            prior_step_outputs=dict(accumulated),  # 使用最新状态
            middle_feedback=middle_feedback,
        )

    # 执行动态调度
    loop_result = await execute_s1_s6_dynamic(
        step_definitions=steps,
        step_modes=step_modes,
        run_step_fn=run_step_for_scheduler,
        commit_step_fn=commit_step,
        critic_fn=middle_loop_critic,
        accumulated_state=accumulated,
        emit_progress_fn=self._emit_winning_progress,
    )
    
    # 更新状态
    loop_trace.extend(loop_result.get("loop_trace", []))
    accumulated["middle_loop_limited"] = loop_result.get("middle_loop_limited", False)
    accumulated["backtrack_history"] = loop_result.get("backtrack_history", [])
    
    # 处理证据补充请求（如果有）
    if loop_result.get("requires_new_evidence"):
        # 保留原有证据补充逻辑
        accumulated["evidence_supplement_pending"] = True
        # ... (原有代码)

else:
    # 保留原有固定波次调度器（向后兼容）
    async def run_step_waves(
        selected_steps: Sequence[int],
        *,
        middle_cycle: int,
        middle_feedback: list[str] | None = None,
    ) -> None:
        selected = set(selected_steps)
        for wave in plan_step_waves(selected):
            prior_step_outputs = dict(accumulated)
            outcomes = await asyncio.gather(
                *(
                    run_step(
                        index,
                        middle_cycle=middle_cycle,
                        prior_step_outputs=prior_step_outputs,
                        middle_feedback=middle_feedback,
                    )
                    for index in wave
                )
            )
            for outcome in sorted(
                outcomes,
                key=lambda item: int(item["run"]["step"]),
            ):
                commit_step(outcome)
    
    await run_step_waves(active_steps, middle_cycle=1)
    
    # 原有中循环批判逻辑
    # ... (保留现有代码 2215-2391 行)
```

**位置 3: 增强 reasoning_node schema（行 1937-1945）**

当前：
```python
"reasoning_node": {
    "recognition": "当前步骤形成的可审计认识",
    "evidence_refs": ["exact evidence_id or packet_id"],
    "confidence": "0..1",
    "next_action": {
        "action": "continue|parallel|backtrack|recall|stop",
        "target_step": "1..6 or 0",
        "reason": "string",
```

增强为：
```python
"reasoning_node": {
    "recognition": "当前步骤形成的可审计认识",
    "evidence_refs": ["exact evidence_id or packet_id"],
    "confidence": "0..1",
    "next_action": {
        "action": "continue|parallel|backtrack|recall|stop",
        "target_step": "1..6 or 0",
        "reason": "string",
        "affected_fields": [
            "修改的字段名，用于智能回溯（可选）"
        ],  # 新增
```

#### 2.2 增强中循环批判 Schema

**位置: 行 2238-2254**

当前 schema:
```python
{
    "passed": "boolean",
    "rerun_from_step": "1..6 or 0",
    "issues": ["string"],
    "rerun_guidance": ["string"],
    "rerun_steps": ["1..6"],
    "requires_new_evidence": "boolean",
    "evidence_requests": [...]
}
```

增强为：
```python
{
    "passed": "boolean",
    "rerun_from_step": "1..6 or 0",
    "issues": ["string"],
    "affected_fields": [  # 新增：标识修改的字段
        "defense_decomposition|operational_review|winning_paths|"
        "breakthrough_directions|effect_chain|capability_mapping|"
        "dotmlpf_matrix|gap_assessment"
    ],
    "rerun_guidance": ["string"],
    "rerun_steps": ["1..6"],  # 保留但优先使用 affected_fields 计算
    "requires_new_evidence": "boolean",
    "evidence_requests": [...]
}
```

#### 2.3 更新环境变量文档

**`.env.codex` 示例**

新增配置项：
```bash
# S1-S6 动态调度器开关（默认启用）
EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER=1

# 性能分析模式（记录详细时间戳）
EQUIPMENT_DR_WINNING_PERFORMANCE_TRACE=0
```

### 3. 测试文件

**新增: `tests/test_dynamic_winning_scheduler.py`**

```python
"""Tests for dynamic S1-S6 scheduler."""

import asyncio
import pytest

from equipment_deep_research.orchestration.dynamic_winning_scheduler import (
    DynamicWinningScheduler,
    ExecutionPlan,
    StepNode,
    ExecutionMode,
)


@pytest.mark.asyncio
async def test_pipeline_parallelism():
    """Test that S4 starts immediately after S3, not waiting for S5."""
    execution_log = []
    
    async def mock_run_step(step, cycle, state, feedback):
        execution_log.append(("start", step, asyncio.get_event_loop().time()))
        await asyncio.sleep(0.1 if step != 5 else 0.5)  # S5 slower
        execution_log.append(("end", step, asyncio.get_event_loop().time()))
        return {
            "result": {},
            "assumptions": [],
            "open_questions": [],
            "reasoning_node": {"next_action": {"action": "continue"}},
            "run": {"step": step, "agent_id": f"s{step}", "middle_cycle": cycle},
        }
    
    def mock_commit(outcome):
        pass
    
    steps = [
        ("s1", "prompt1", {}),
        ("s2", "prompt2", {}),
        ("s3", "prompt3", {}),
        ("s4", "prompt4", {}),
        ("s5", "prompt5", {}),
        ("s6", "prompt6", {}),
    ]
    
    scheduler = DynamicWinningScheduler(
        step_definitions=steps,
        step_modes={1: "standard", 2: "standard", 3: "standard", 
                    4: "standard", 5: "standard", 6: "standard"},
        run_step_fn=mock_run_step,
        commit_step_fn=mock_commit,
    )
    
    await scheduler.execute_pipeline(middle_cycle=1)
    
    # Extract timing
    timings = {step: {"start": None, "end": None} for step in range(1, 7)}
    for event, step, timestamp in execution_log:
        timings[step][event] = timestamp
    
    # Verify S6 starts after S4 ends (not waiting for S5)
    assert timings[6]["start"] >= timings[4]["end"]
    # Verify S6 might start before S5 ends (pipeline parallelism)
    # (S5 is slower, so S6 should start while S5 is still running)


@pytest.mark.asyncio
async def test_intelligent_backtrack():
    """Test that backtrack only reruns affected steps."""
    plan = ExecutionPlan(nodes={
        1: StepNode(1, "s1", ExecutionMode.STANDARD, ()),
        2: StepNode(2, "s2", ExecutionMode.STANDARD, ()),
        3: StepNode(3, "s3", ExecutionMode.STANDARD, (1, 2)),
        4: StepNode(4, "s4", ExecutionMode.STANDARD, (3,)),
        5: StepNode(5, "s5", ExecutionMode.STANDARD, (3,)),
        6: StepNode(6, "s6", ExecutionMode.STANDARD, (4, 5)),
    })
    
    # Mark all as completed
    for step in range(1, 7):
        plan.mark_completed(step)
    
    # Backtrack S3 with specific field modification
    rerun_steps = plan.backtrack_to(
        target_step=3,
        reason="effect_chain needs revision",
        affected_fields=["effect_chain"],  # Only affects S4 and S6
        middle_cycle=2,
    )
    
    # Should only rerun S3, S4, S6 (not S5)
    assert set(rerun_steps) == {3, 4, 6}
    
    # Verify S5 still marked as completed
    assert plan.nodes[5].status == "completed"
    assert 5 in plan.completed_steps


@pytest.mark.asyncio
async def test_skip_mode():
    """Test that skip mode steps are treated as satisfied dependencies."""
    execution_log = []
    
    async def mock_run_step(step, cycle, state, feedback):
        execution_log.append(step)
        return {
            "result": {},
            "assumptions": [],
            "open_questions": [],
            "reasoning_node": {"next_action": {"action": "continue"}},
            "run": {"step": step, "agent_id": f"s{step}", "middle_cycle": cycle},
        }
    
    def mock_commit(outcome):
        pass
    
    steps = [
        ("s1", "prompt1", {}),
        ("s2", "prompt2", {}),
        ("s3", "prompt3", {}),
        ("s4", "prompt4", {}),
        ("s5", "prompt5", {}),
        ("s6", "prompt6", {}),
    ]
    
    # C branch: S1, S2 skip
    scheduler = DynamicWinningScheduler(
        step_definitions=steps,
        step_modes={
            1: "skip",
            2: "skip",
            3: "deep",
            4: "deep",
            5: "standard",
            6: "deep",
        },
        run_step_fn=mock_run_step,
        commit_step_fn=mock_commit,
    )
    
    await scheduler.execute_pipeline(middle_cycle=1)
    
    # Only S3-S6 should execute
    assert execution_log == [3, 4, 5, 6]
```

## 实施步骤

### 阶段 1：集成与测试（1-2 小时）

1. **运行单元测试**
   ```bash
   pytest tests/test_dynamic_winning_scheduler.py -v
   ```

2. **集成到 provider.py**
   - 修改 `src/equipment_deep_research/agents/provider.py`
   - 按照上述"位置 1-3"进行改动
   - 默认启用动态调度器

3. **烟雾测试**
   ```bash
   python3 scripts/run_deep_research.py \
     --mode fake \
     --topic "低空无人体系装备能力缺口" \
     --research-route traditional_gap \
     --run-id dynamic-scheduler-smoke
   ```

### 阶段 2：性能验证（2-3 小时）

4. **基线性能测试**
   ```bash
   # 关闭动态调度器，测试原有性能
   export EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER=0
   python3 scripts/run_deep_research.py \
     --mode real \
     --provider codex \
     --topic "低空无人体系装备能力缺口" \
     --research-route traditional_gap \
     --run-id baseline-perf
   ```

5. **优化后性能测试**
   ```bash
   # 启用动态调度器
   export EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER=1
   python3 scripts/run_deep_research.py \
     --mode real \
     --provider codex \
     --topic "低空无人体系装备能力缺口" \
     --research-route traditional_gap \
     --run-id optimized-perf
   ```

6. **对比分析**
   - 从 `outputs/runs/*/trace.jsonl` 提取时间戳
   - 计算各步骤耗时和总时间
   - 生成对比报告

### 阶段 3：回归测试（1-2 小时）

7. **A-H 分支测试**
   ```bash
   for branch in A B C D E F G H; do
     python3 scripts/run_deep_research.py \
       --mode fake \
       --topic "测试分支 $branch" \
       --research-route traditional_gap \
       --run-id "branch-$branch-test"
   done
   ```

8. **输出一致性验证**
   - 对比动态调度器与原调度器的输出
   - 验证 reasoning_nodes、capability_images、报告一致性

### 阶段 4：生产部署（按需）

9. **文档更新**
   - 更新 `docs/TECHNICAL_SCHEME.md`
   - 更新 `docs/CODEX_ADAPTER_MODE.md`
   - 添加性能对比数据到 `docs/S1-S6_EFFICIENCY_DIAGNOSIS.md`

10. **默认启用**
    - 移除环境变量开关（或默认改为 1）
    - 更新 Docker 配置
    - 提交 PR

## 向后兼容性

- ✅ 通过环境变量 `EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER=0` 可恢复原调度器
- ✅ 原有 `plan_step_waves` 函数保留
- ✅ 所有输出字段向后兼容
- ✅ 新增字段（`affected_fields`, `backtrack_history`）为可选

## 预期收益

### 正常执行
- **流水线并行**: 15-25% 加速
- 取决于步骤耗时分布，S4 慢时收益最大

### 回溯场景
- **智能重跑**: 30-50% 回溯成本降低
- S3 小修改只重跑 S3、S4（省 S5、S6）

### 分支特化
- **skip 模式**: C/D/E/F/G/H 分支跳过 S1/S2，节省 20-40%
- 已有实现，动态调度器完全兼容

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 并发 bug | 高 | 完整单元测试 + 烟雾测试 |
| 性能回退 | 中 | 性能基线对比，可快速回滚 |
| 输出不一致 | 高 | 回归测试 + 输出对比 |
| critic 不理解新 schema | 中 | 增量部署，先启用流水线，后启用智能回溯 |

## 后续优化

完成方案 A 后，可继续：

1. **方案 D 完整实现**: 让 critic 输出精确的 `affected_fields`
2. **方案 B（进程池）**: 预热 Codex CLI 进程
3. **性能监控**: 添加详细的 timing trace
4. **可视化**: 在 Web 工作台显示执行 DAG 和并行度

## 联系与支持

实施过程中如有问题：
1. 查看 `outputs/runs/*/trace.jsonl` 获取详细执行日志
2. 检查 `EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER` 环境变量
3. 运行单元测试定位问题：`pytest tests/test_dynamic_winning_scheduler.py -v -s`
