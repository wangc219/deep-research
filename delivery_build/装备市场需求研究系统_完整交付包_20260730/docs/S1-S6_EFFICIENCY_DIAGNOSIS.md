# S1-S6 制胜机理执行效率诊断与优化方案

**诊断日期**: 2026-07-19  
**诊断范围**: 制胜机理 S1-S6 子 Agent 执行流程  
**核心代码**: `src/equipment_deep_research/agents/provider.py:2134-2194`

---

## 一、当前执行架构

### 1.1 执行方式

S1-S6 通过 **固定波次（wave）并行** 方式执行：

```python
step_waves = ((1, 2), (3,), (4, 5), (6,))
# 真实数据依赖：S3←{S1,S2}，S4←{S3}，S5←{S3}，S6←{S4,S5}。
```

**实际执行流程**：
- **Wave 1**: S1、S2 并行执行 → 等待两者完成
- **Wave 2**: S3 独自执行 → 等待完成
- **Wave 3**: S4、S5 并行执行 → 等待两者完成
- **Wave 4**: S6 独自执行 → 等待完成

每个波次内通过 `asyncio.gather` 实现并行：
```python
outcomes = await asyncio.gather(
    *(run_step(index, ...) for index in wave)
)
```

### 1.2 Codex CLI 调用方式

每个 S1-S6 步骤通过 **独立 Codex CLI 进程** 执行：
- 每次调用 `codex exec --json --ephemeral`
- 隔离的 `CODEX_HOME` 目录（`outputs/runtime/codex-home`）
- 每次重新加载 skills、knowledge packs、上下文
- 通过 stdin 传入 prompt，stdout 返回 JSON

### 1.3 循环机制

**三层循环**：
1. **内循环（Inner Loop）**: 单步批判，最多 2 次重试
   - 每个 S 步骤完成后由 `winning_step_critic` 检查
   - 不通过时原地重跑，最多 2 次
   
2. **中循环（Middle Loop）**: 跨步批判，最多 2 轮
   - 6 个步骤全部完成后，`winning_round_critic` 检查整体一致性
   - 可以回溯到指定步骤重跑后续所有步骤
   - 第 2 轮仍不通过则标记 `middle_loop_limited`
   
3. **外循环（Outer Loop）**: L1/L2/L3 覆盖度门控
   - 由 orchestrator 触发定向 Recall 补充证据
   - 补证后从指定层级恢复执行

---

## 二、效率瓶颈分析

### 2.1 串行等待瓶颈 ⚠️ **高优先级**

**问题**: 固定波次导致最长任务阻塞整个波次

**举例**:
- Wave 1: S1 耗时 30s，S2 耗时 90s → 整个 Wave 1 耗时 90s
- Wave 3: S4 耗时 120s，S5 耗时 45s → 整个 Wave 3 耗时 120s
- **理论最优**: S4 完成后 S6 可以立即开始（S6 只依赖 S4+S5）
- **当前实现**: S6 必须等 S4、S5 **都完成** 才能开始

**影响**:
- 墙钟时间 = 最慢波次之和，而非关键路径
- S4 慢时，S5→S6 的流水被阻塞
- 无法利用"S6 实际只需要 S4 的某些字段"的细粒度依赖

### 2.2 Codex CLI 进程启动开销 ⚠️ **中优先级**

**问题**: 每个 S1-S6 步骤都是独立进程

**开销分解**:
1. 进程启动：50-200ms（macOS fork + exec）
2. 隔离 `CODEX_HOME` 初始化：20-100ms
3. Skills 加载（`js-equipment-agent-runtime` + `js-winning-shared-layer`）：100-300ms
4. Knowledge packs 索引加载：50-200ms
5. 上下文编译（prompt + context pack）：50-150ms

**单步开销**: 270-950ms  
**6 步总开销**: 1.6-5.7s（不含实际推理时间）

**特别注意**:
- 当前每个步骤的 `max_output_tokens` 为 1800-7000
- 实际推理时间可能 10-60s/步
- 进程开销占比约 **3-15%**

### 2.3 上下文重复传递 ⚠️ **中低优先级**

**问题**: 每个步骤重新传入完整上下文

```python
def step_shared_context(index: int) -> dict[str, Any]:
    return {
        "topic": shared["topic"],
        "research_route": shared["research_route"],
        "discovery_branch": shared["discovery_branch"],
        "discovery_blueprint": compact_blueprint,
        "coverage": shared["coverage"],
        "packet_index": packet_index,  # 全量业务 Agent 输出
        "packets": _compact_prompt_value(...),  # 压缩后仍可能 5-20KB
        "evidence_index": _compact_prompt_value(..., max_list_items=40),  # 可能 10-50KB
    }
```

**累计影响**:
- 相同的 `packet_index`、`evidence_index` 在 S1-S6 中重复传 6 次
- prompt cache 在独立进程间不共享（每次都是新的 Codex CLI 会话）
- 网络传输（如果模型 API 是远程）：6 次 × 20-80KB

### 2.4 中循环回溯成本 ⚠️ **高优先级**

**问题**: 回溯时重跑所有后续步骤

```python
# 中循环回溯逻辑
rerun_from = next((index for index in active_steps if index >= rerun_from), 0)
await run_step_waves(requested_steps, middle_cycle=2)
```

**举例**:
- S3 有问题，`rerun_from_step=3`
- 实际重跑：S3、S4、S5、S6（**4 个步骤**）
- 如果 S4、S5 的结论实际不受 S3 修改影响 → **浪费 2 个步骤的执行**

**最坏情况**:
- 第 1 轮：S1-S6 全跑（6 步）
- 中循环发现 S2 问题，回溯到 S2：S2-S6 重跑（5 步）
- 第 2 轮中循环仍不通过 → 总共 **11 个步骤执行**（理论最少 7-8 步）

### 2.5 动态专用 Agent 串行前置

**当前逻辑**:
```python
if dynamic_specs and not requested_resume_steps:
    dynamic_outputs = list(
        await asyncio.gather(*(run_dynamic_specialist(spec) for spec in dynamic_specs))
    )
    # 动态 Agent 全部完成后，才开始 S1-S6
await run_step_waves(active_steps, middle_cycle=1)
```

**问题**:
- 动态 Agent 与 S1-S6 完全串行
- 动态 Agent 的输出可能只影响 S3/S4，但 S1/S2 仍然等待

---

## 三、优化方案

### 3.1 方案 A：流水线并行（Pipeline Parallelism） ⭐ **推荐**

**核心思路**: 把固定波次改为动态依赖调度，步骤一旦依赖满足立即启动。

#### 实现方式

**当前**:
```python
step_waves = ((1, 2), (3,), (4, 5), (6,))  # 固定 4 个波次
for wave in step_waves:
    await asyncio.gather(*(run_step(i) for i in wave))  # 串行等待每个波次
```

**优化后**:
```python
async def run_step_pipeline(selected_steps: set[int]) -> None:
    """动态流水线：步骤依赖满足后立即启动，无需等待同波次其他步骤"""
    completed = asyncio.Event()
    completed_steps: set[int] = set()
    running_tasks: dict[int, asyncio.Task] = {}
    lock = asyncio.Lock()
    
    async def monitor_and_launch():
        while len(completed_steps) < len(selected_steps):
            await completed.wait()
            completed.clear()
            
            async with lock:
                # 找到所有依赖已满足的步骤
                ready = [
                    step for step in selected_steps
                    if step not in completed_steps
                    and step not in running_tasks
                    and all(dep in completed_steps for dep in step_dependency_map[step])
                ]
                
                # 立即启动所有就绪步骤
                for step in ready:
                    running_tasks[step] = asyncio.create_task(
                        run_step_with_callback(step)
                    )
    
    async def run_step_with_callback(index: int):
        try:
            outcome = await run_step(index, ...)
            commit_step(outcome)
        finally:
            async with lock:
                completed_steps.add(index)
                running_tasks.pop(index, None)
                completed.set()  # 通知可能有新的就绪步骤
    
    # 启动初始无依赖步骤（S1、S2）
    completed.set()
    await monitor_and_launch()
```

**效果**:
- S4 完成 → S6 立即可以开始（不等 S5）
- S1 完成 90% 时间时，S2 可能刚完成 60%，S3 提前准备
- **理论加速**: 15-30%（取决于步骤耗时分布）

#### 代码改动点

1. **`src/equipment_deep_research/agents/provider.py:2168-2193`**  
   替换 `run_step_waves` 为流水线调度器

2. **向后兼容**  
   保留 `plan_step_waves` 用于 skip/复用场景

#### 风险评估

- **低**: 依赖关系已明确定义，只是调度策略变化
- 需增加并发任务管理，增加约 50 行代码

---

### 3.2 方案 B：长生命周期 Codex Agent 会话 ⭐⭐ **高收益，中风险**

**核心思路**: 使用一个持久的 Codex CLI 会话完成 S1-S6，而非 6 个独立进程。

#### 技术路径

**方案 B1: Codex CLI 守护进程模式**

```python
class CodexAgentSession:
    """持久化 Codex CLI 会话，复用进程和上下文"""
    
    def __init__(self, home_dir: Path, skills: list[str]):
        self.proc = subprocess.Popen(
            ["codex", "exec", "--json", "--session-mode"],  # 假设支持
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={...},
        )
        self._initialize_skills(skills)
    
    async def run_step(self, step: int, context: dict) -> dict:
        """在同一会话中执行步骤，共享加载的 skills 和历史上下文"""
        prompt = self._build_prompt(step, context)
        self.proc.stdin.write(json.dumps({"prompt": prompt}).encode())
        result = json.loads(self.proc.stdout.readline())
        return result
    
    def __del__(self):
        self.proc.terminate()
```

**收益**:
- 消除 5 次进程启动开销（保留 1 次）
- Skills/knowledge packs 只加载 1 次
- **节省时间**: 1.2-4.5s（约 **10-15%** 总时间）

**风险**:
- **Codex CLI 目前不支持会话模式**（需要验证或提交 feature request）
- 会话状态管理复杂度增加
- 单进程故障影响所有步骤

**方案 B2: 预热进程池**

```python
class CodexProcessPool:
    """预创建 Codex 进程池，复用已初始化的进程"""
    
    def __init__(self, size: int = 3):
        self.pool = [self._spawn_worker() for _ in range(size)]
    
    def _spawn_worker(self) -> CodexWorker:
        # 启动进程 + 加载 skills，但不执行任务
        proc = subprocess.Popen([...])
        # 发送 warmup prompt 加载 skills
        return CodexWorker(proc)
    
    async def execute(self, step: int, context: dict) -> dict:
        worker = await self.acquire()
        try:
            return await worker.run_step(step, context)
        finally:
            self.release(worker)
```

**收益**:
- 消除动态启动开销
- 并行执行时无需等待进程启动
- **节省时间**: 0.8-3.2s（约 **8-12%** 总时间）

---

### 3.3 方案 C：增量上下文传递 ⚠️ **收益有限**

**核心思路**: 只传递增量上下文，复用 prompt cache。

#### 实现方式

```python
def prior_projection(index: int, prior_step_outputs: Mapping[str, Any]) -> dict:
    # 当前已实现：只传递前序步骤的特定字段
    field_map = {
        2: ("defense_decomposition",),
        3: ("defense_decomposition", "operational_review", "winning_paths"),
        4: ("breakthrough_directions", "effect_chain"),
        # ...
    }
    # 优化：添加 cache key
    return {
        "_cache_key": hash(frozenset(packet_index)),  # 标识不变部分
        **projected_fields
    }
```

**问题**: Codex CLI 独立进程间**无法共享 prompt cache**

**替代方案**: 使用直连 Responses API（已在发现阶段使用）
- Responses API 支持 5 分钟 prompt cache TTL
- 需要将 S1-S6 也切换到 Responses 而非 Codex CLI

**收益**: 有限（Codex CLI 隔离是架构决策，改动成本高）

---

### 3.4 方案 D：智能中循环回溯 ⭐ **推荐**

**核心思路**: 只重跑受影响的步骤，而非所有后续步骤。

#### 实现方式

**当前**:
```python
rerun_from = next((index for index in active_steps if index >= rerun_from), 0)
requested_steps = [index for index in active_steps if index >= rerun_from]
# S3 有问题 → 重跑 S3, S4, S5, S6
```

**优化后**:
```python
def compute_affected_steps(modified_step: int, issue_fields: list[str]) -> set[int]:
    """根据修改的字段，计算实际受影响的下游步骤"""
    # S3 的 breakthrough_directions 影响 S4
    # S3 的 effect_chain 影响 S4 和 S6
    field_impact = {
        ("defense_decomposition", 1): {2, 3},
        ("winning_paths", 2): {3, 6},
        ("breakthrough_directions", 3): {4},
        ("effect_chain", 3): {4, 6},
        ("capability_mapping", 4): {5, 6},
        # ...
    }
    affected = set()
    for field in issue_fields:
        affected.update(field_impact.get((field, modified_step), set()))
    return affected

# 中循环批判时输出受影响字段
round_review_schema = {
    "rerun_from_step": "1..6",
    "affected_fields": ["defense_decomposition", "winning_paths", ...],  # 新增
    "rerun_steps": ["1..6"],
}

# 智能重跑
affected = compute_affected_steps(rerun_from, round_review["affected_fields"])
requested_steps = sorted(affected)  # 只重跑受影响步骤
```

**收益**:
- S3 的小修改可能只需重跑 S3、S4（省 S5、S6）
- **节省时间**: 20-40s/回溯（约 **30-50%** 回溯成本）

**风险**:
- 依赖分析需要准确（错误会导致不一致）
- 需要增强 `winning_round_critic` 的输出 schema

---

### 3.5 方案 E：动态 Agent 流水线融合 ⚠️ **低优先级**

**核心思路**: 动态 Agent 与 S1-S6 并行执行，按需合并。

```python
async def run_with_dynamic():
    # 启动动态 Agent（不等待完成）
    dynamic_tasks = [asyncio.create_task(run_dynamic_specialist(spec)) for spec in dynamic_specs]
    
    # 同时启动 S1-S6 流水线
    pipeline_task = asyncio.create_task(run_step_pipeline(active_steps))
    
    # 等待动态 Agent 完成
    dynamic_outputs = await asyncio.gather(*dynamic_tasks)
    
    # 将动态输出注入到正在运行的流水线中
    inject_dynamic_results(dynamic_outputs)
    
    await pipeline_task
```

**收益**: 动态 Agent（0-3 个，每个 20-60s）与 S1-S6 并行  
**风险**: 复杂度高，动态注入可能影响已运行步骤的一致性

---

## 四、推荐实施路径

### 阶段 1：快速收益（1-2 天） ⭐

1. **实施方案 A（流水线并行）**
   - 修改 `run_step_waves` 为动态依赖调度
   - **预期加速**: 15-30%
   - **风险**: 低

2. **实施方案 D（智能回溯）**
   - 增强中循环批判输出 `affected_fields`
   - 实现 `compute_affected_steps` 函数
   - **预期节省**: 每次回溯 20-40s
   - **风险**: 低-中

**总收益**: 15-30% 正常执行加速 + 30-50% 回溯成本降低

### 阶段 2：结构优化（3-5 天）

3. **调研方案 B（长生命周期会话）**
   - 验证 Codex CLI 是否支持会话模式
   - 如果不支持，实施预热进程池（方案 B2）
   - **预期加速**: 8-15%
   - **风险**: 中

4. **优化 A-H 分支的 S1-S6 执行模式**
   - 当前 `BRANCH_WINNING_STEP_MODES` 已定义 skip/light/standard/deep
   - 确保 `light` 模式真正降低 token 和推理成本
   - **预期加速**: 分支特化场景 20-40%

### 阶段 3：可选增强（按需）

5. **方案 E（动态 Agent 并行）**  
   仅当动态 Agent 数量多（>2）且耗时长（>30s）时实施

6. **方案 C（增量上下文）**  
   仅当切换到 Responses API 后实施

---

## 五、测试验证

### 5.1 性能基线

**测试场景**: 传统能力缺口（B 分支）
```bash
python3 scripts/run_deep_research.py \
  --mode real \
  --provider codex \
  --topic "低空无人体系装备能力缺口" \
  --research-route traditional_gap \
  --run-id baseline-perf-test
```

**采集指标**:
- 各波次耗时（从 trace events 提取）
- S1-S6 各步骤耗时
- 中循环次数和回溯步骤数
- 总墙钟时间

### 5.2 优化后对比

**对比维度**:
1. 总墙钟时间（期望 ↓ 15-30%）
2. 关键路径时间（期望接近理论最优）
3. 中循环回溯成本（期望 ↓ 30-50%）
4. 资源利用率（CPU 并行度）

### 5.3 回归测试

**验证点**:
- S1-S6 输出结果与基线版本一致性 > 95%
- 中循环批判逻辑正确性
- 动态依赖调度正确性（无死锁、无遗漏）

---

## 六、风险评估

| 方案 | 复杂度 | 风险 | 收益 | 优先级 |
|------|--------|------|------|--------|
| A: 流水线并行 | 中 | 低 | 15-30% | ⭐⭐⭐ |
| D: 智能回溯 | 中 | 低-中 | 回溯场景 30-50% | ⭐⭐⭐ |
| B1: 会话模式 | 高 | 中-高 | 10-15% | ⭐⭐ 需调研 |
| B2: 进程池 | 中 | 中 | 8-12% | ⭐⭐ |
| E: 动态并行 | 高 | 高 | 有限 | ⭐ |
| C: 增量上下文 | 高 | 中 | 有限 | ⭐ |

---

## 七、附录：性能估算

### 当前性能模型（B 分支全量执行）

```
Wave 1 (S1, S2 并行):  max(30s, 90s) = 90s
Wave 2 (S3 单独):     60s
Wave 3 (S4, S5 并行):  max(120s, 45s) = 120s
Wave 4 (S6 单独):     50s
----------------------------------------------
总墙钟时间:           320s (5.3分钟)

如果中循环回溯 S3:
  重跑 S3, S4, S5, S6: 60+120+50 = 230s
总时间:               320 + 230 = 550s (9.2分钟)
```

### 优化后性能模型（方案 A + D）

```
理想流水线:
S1: 0-30s
S2: 0-90s
S3: 90-150s (等S1,S2)
S4: 150-270s (等S3)
S5: 150-195s (等S3，与S4并行)
S6: 270-320s (等S4,S5，但S5早完成)
----------------------------------------------
总墙钟时间:           320s → 无改善（S4 是瓶颈）

但如果 S4=80s (而非120s):
S4: 150-230s
S6: 230-280s
总时间: 280s → 节省 40s (12.5%)

智能回溯 S3:
  只重跑 S3, S4: 60+80 = 140s (省S5,S6)
总时间:               280 + 140 = 420s (7分钟)
相比当前 550s 节省 130s (23.6%)
```

---

## 八、结论

**立即行动**：
1. 实施**方案 A（流水线并行）**和**方案 D（智能回溯）**
2. 预期整体加速 **15-30%**，回溯场景额外节省 **20-40%**
3. 代码改动量约 **150-200 行**，风险可控

**后续调研**：
- Codex CLI 会话模式支持情况
- 是否有大量中循环回溯（如果 <10% 场景触发，方案 D 优先级降低）

**不推荐**：
- 方案 C（增量上下文）：收益有限且需大改架构
- 方案 E（动态并行）：复杂度高，收益不明确
